"""抓取机构官网页面并输出通用地址证据。"""

import re
import time
from urllib.parse import urlparse
from .access import (
    BROWSER_HEADERS,
    USER_AGENT,
    fetch_direct_content,
    is_url_in_domains,
    normalize_domain,
)

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


CHROME_ARGS = ['--disable-blink-features=AutomationControlled']


def decode_html_content(content, http_charset=''):
    """按 BOM、HTTP 头或 HTML 声明的字符集解码直连 HTML，最后回退到 UTF-8。"""
    raw = bytes(content or b'')
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig', errors='replace')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16', errors='replace')
    head = raw[:8192].decode('ascii', errors='ignore')
    match = re.search(
        r'<meta[^>]+charset\s*=\s*["\']?\s*([\w-]+)', head,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r'content-type[^>]+charset\s*=\s*["\']?\s*([\w-]+)',
            head,
            re.IGNORECASE,
        )
    encoding = (
        str(http_charset or '').strip()
        or (match.group(1) if match else '')
        or 'utf-8'
    )
    try:
        return raw.decode(encoding, errors='replace')
    except LookupError:
        return raw.decode('utf-8', errors='replace')


def normalize_lines(value):
    """清理文本空白并保留有效换行。"""
    lines = []
    for line in str(value or '').replace('\xa0', ' ').replace('\u3000', ' ').splitlines():
        line = re.sub(r'[ \t\f\v]+', ' ', line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return '\n'.join(lines)


def fetch_browser_page(page, url):
    """打开官网页面，必要时用同一浏览器上下文回填原始 HTML。"""
    for attempt in range(2):
        try:
            response = page.goto(url, timeout=40000, wait_until='domcontentloaded')
            page.wait_for_selector('body', state='attached', timeout=5000)
            return response
        except PlaywrightTimeoutError:
            if attempt == 0:
                continue
        except PlaywrightError:
            pass
        break

    api_response = page.request.get(
        url, timeout=40000,
        headers={'User-Agent': USER_AGENT, **BROWSER_HEADERS},
    )
    fallback_url = api_response.url

    def fulfill_document_only(route):
        request = route.request
        if request.is_navigation_request() and request.url == fallback_url:
            route.fulfill(response=api_response)
        else:
            route.abort()

    page.route('**/*', fulfill_document_only)
    try:
        response = page.goto(
            fallback_url, timeout=40000, wait_until='domcontentloaded'
        )
        page.wait_for_selector('body', state='attached', timeout=5000)
        return response
    finally:
        page.unroute('**/*', fulfill_document_only)


def format_page_error(error):
    """将页面访问异常压缩为单行警告。"""
    return f'页面访问失败：{normalize_lines(str(error)).replace(chr(10), " | ")}'


class HttpResponseShim:
    """为直连 HTML 回填提供 Playwright 响应所需的状态字段。"""

    def __init__(self, status, url, access_attempts=()):
        self.status = status
        self.url = url
        self.access_attempts = list(access_attempts)


def fetch_http_page(page, url, preferred_method=None):
    """通过 urllib 或 curl 获取 HTML 并回填当前页面。"""
    body, final_url, status, attempts, charset = fetch_direct_content(
        url, preferred_method=preferred_method,
    )
    page.set_content(
        decode_html_content(body, charset),
        wait_until='domcontentloaded',
    )
    return HttpResponseShim(status, final_url, attempts)


def collect_official_page_data(page, extra_address_labels=()):
    """收集通用地址证据、结构上下文和页面链接。"""
    labels = [str(item).strip() for item in extra_address_labels if str(item).strip()]
    return page.evaluate(r"""
    labels => {
      const extras = new Set(labels.map(v => v.replace(/\s+/g, '')));
      const excluded = new Set(['SCRIPT','STYLE','NOSCRIPT','SVG','PATH']);
      const stop = /\s*(?:(?:邮政编码|邮编|联系方式|查号台|传真|邮箱|电子邮箱|E[_-]?mail|版权所有|版权|Copyright|[\p{Script=Han}]?ICP备)\s*[：:]?|(?:(?!号)[\p{Script=Han}]){0,8}电话\s*[：:]|©)/iu;
      const contact = /(?:电话|联系方式|传真|邮编|邮政编码|邮箱|E[_-]?mail)\s*[：:]|(?:\+?86[- ]?)?0\d{2,3}[- ]?\d{7,8}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/i;
      const bad = /(?:ICP备|公安备案|网站标识码|recordcode|区号|https?:\/\/)|(?:^|\s)(?:var|let|const)\s+\w+\s*=/i;
      const admin = /(?:省|自治区|特别行政区|市|州|区|县|旗|街道|镇|乡|苏木|村|社区)/;
      const place = /(?:路|街|道|巷|弄|号|里|园|开发区|大厦|广场|园区|院区|楼|村|社区)/;
      const routePlace = /(?:路|街|道|巷|弄|里|开发区)/;
      const elements = [...(document.body?.querySelectorAll('*') || [])].filter(e => !excluded.has(e.tagName));
      const order = new Map(elements.map((e, i) => [e, i]));
      const blockIds = new WeakMap(); let blockCount = 0;

      function clean(v) { return String(v || '').replace(/[\u00A0\u3000]/g,' ').replace(/\r/g,'').split('\n').map(x=>x.replace(/[ \t]+/g,' ').trim()).filter(Boolean).join('\n'); }
      function text(e) { return clean(e?.innerText) || clean(e?.textContent); }
      function hint(e) { return `${e.id||''} ${typeof e.className==='string'?e.className:''}`.toLowerCase(); }
      function visible(e) { const s=getComputedStyle(e); return s.display!=='none'&&s.visibility!=='hidden'&&e.getClientRects().length>0; }
      function region(e) { for(let n=e;n;n=n.parentElement){const r=String(n.getAttribute('role')||'').toLowerCase();if(n.tagName==='FOOTER'||r==='contentinfo')return 'semantic_footer';const h=hint(n);if(/(?:^|[ _-])(?:footer|foot|bottom|bot|copyright)(?:$|[ _-])/.test(h))return 'footer_like';if(/(?:^|[ _-])(?:contact|address)(?:$|[ _-])/.test(h))return 'contact';}return 'body'; }
      function normLabel(v) { return clean(v).replace(/[\s：:]/g,''); }
      function isLabel(v) { const x=normLabel(v); return (x.length<=40&&[...extras].some(label=>x.endsWith(label)))||x==='地址'||(x.endsWith('地址')&&x.length<=14&&/^[\p{Script=Han}A-Za-z0-9（）()]+$/u.test(x)); }
      function gluedLabel(left) {
        const boundary=Math.max(
          left.lastIndexOf('号'),left.lastIndexOf('）'),left.lastIndexOf(')')
        );
        if(boundary<0)return '';
        const candidate=left.slice(boundary+1).trim();
        return isLabel(candidate)?candidate:'';
      }
      function inlines(v) {
        const found=[];
        for(const line of clean(v).split('\n')){
          const marks=[];
          for(let i=0;i<line.length;i++){
            const left=line.slice(0,i).trim();
            let label='';
            if(/[：:]/.test(line[i])){
              const spaced=left.match(/地\s*址$/);
              const tail=left.split(/\s+/).at(-1)||'';
              const glued=gluedLabel(left);
              label=(glued|| (isLabel(tail)?tail
                :(spaced?spaced[0]:(isLabel(left)?left:''))));
            }else if(line[i]==='为'){
              const boundary=Math.max(
                left.lastIndexOf('，'),left.lastIndexOf(','),
                left.lastIndexOf('。'),left.lastIndexOf('；'),left.lastIndexOf(';')
              );
              const candidate=left.slice(boundary+1).trim();
              if(isLabel(candidate))label=candidate;
            }
            if(label)marks.push({
              label,start:line.lastIndexOf(label,i),valueStart:i+1
            });
          }
          for(let i=0;i<marks.length;i++){
            const value=line.slice(
              marks[i].valueStart,marks[i+1]?.start??line.length
            ).trim();
            if(value)found.push({label:marks[i].label,value,line});
          }
        }
        return found;
      }
      function inline(v) { return inlines(v)[0]||null; }
      function sameInlineField(a, b) {
        return normLabel(a.label)===normLabel(b.label);
      }
      function richerInlineAncestor(e, match) {
        const value=cleanAddress(match.value);
        for(let n=e.parentElement,d=0;n&&n!==document.body&&d<3;n=n.parentElement,d++){
          const x=text(n);
          if(x.length>500)break;
          if(inlines(x).some(parentMatch=>{
            const parentValue=cleanAddress(parentMatch.value);
            return sameInlineField(match,parentMatch)
              &&!/[：:]/.test(parentValue)
              &&parentValue.length>value.length
              &&parentValue.startsWith(value);
          }))return true;
        }
        return false;
      }
      function inlineOwnedByChild(e, match) {
        const value=cleanAddress(match.value);
        return [...e.children].some(child=>inlines(text(child)).some(childMatch=>{
          if(!sameInlineField(match,childMatch))return false;
          const childValue=cleanAddress(childMatch.value);
          return childValue.length>=value.length
            || (/[：:]/.test(value)&&value.startsWith(childValue));
        }));
      }
      function configuredSuffix(v) {
        const x=clean(v).replace(/\n/g,' ');
        const match=x.match(/[（(]([^（）()]{1,40})[）)]$/);
        if(!match||[...x.slice(0,match.index)].some(c=>'，,。；;！？!?'.includes(c)))return '';
        const label=normLabel(match[1]);
        return [...extras].some(extra=>label.endsWith(extra))?match[1]:'';
      }
      function cleanAddress(v, label='') { let x=clean(v).replace(/\n/g,' ').split(stop,1)[0].split('。',1)[0].replace(/^[—–-]+\s*/,'').trim();if(label){const i=x.indexOf(label);if(i>=0){const rest=x.slice(i+label.length),s=rest.search(/[：:]/);x=(s>=0?rest.slice(s+1):rest).trim();}}x=x.replace(/\s*\d?空{2,}\s*$/,'');return x.replace(/\s*(?:点击)?查看(?:交通)?指引\s*$/,'').replace(/\s*[\[【][^\]】]*(?:交通图|地图)[^\]】]*[\]】]\s*$/,'').replace(/\s*[（(]\d{6}[）)]\s*$/,'').replace(/\s*[（(][^（）()]*(?:地铁|公交|高速|BRT|城轨)[^（）()]*[）)]\s*$/i,'').replace(/\s*[（(]?0\d{2,3}[）)]?[- ]?\d{7,8}\s*$/,'').replace(/\s*[\[【（(]\s*$/,'').replace(/[|｜，,；;。]+$/,'').trim(); }
      function looks(v, strength) { const raw=clean(v),x=cleanAddress(v);if(strength!=='strong'&&raw.includes('\n'))return false;return x.length>=4&&x.length<=160&&!bad.test(x)&&!/(?:\.{2,}|…+)$/.test(x)&&admin.test(x)&&(strength==='strong'||routePlace.test(x)||(place.test(x)&&/\d/.test(x))||x.split(admin).length>3); }
      function excludedContext(e) { let n=e?.previousElementSibling;for(let i=0;n&&i<3;i++,n=n.previousElementSibling){if(/举报/.test(text(n)))return true;}return false; }
      function short(e, relation, distance) { if(!e||excluded.has(e.tagName))return null;const x=text(e);return !x||x.length>80||contact.test(x)?null:{text:x,relation,distance,tag:e.tagName}; }
      function context(e) { const before=[],after=[];let p=e.previousElementSibling,n=e.nextElementSibling;for(let d=1;d<=2;d++){const a=short(p,'previous_sibling',d),b=short(n,'next_sibling',d);if(a)before.push(a);if(b)after.push(b);p=p?.previousElementSibling;n=n?.nextElementSibling;}for(let a=e.parentElement,d=1;a&&a!==document.body&&d<=3;a=a.parentElement,d++){const h=a.querySelector(':scope > h1,:scope > h2,:scope > h3,:scope > h4,:scope > h5,:scope > h6,:scope > dt'),c=short(h,'ancestor_heading',d);if(c&&!before.some(x=>x.text===c.text))before.push(c);}return {before,after}; }
      function block(e) { let n=e;while(n&&n!==document.body&&!['FOOTER','LI','TR','DL','SECTION','ARTICLE'].includes(n.tagName)&&region(n)==='body')n=n.parentElement;n=n||e.parentElement||e;if(!blockIds.has(n))blockIds.set(n,`block_${++blockCount}`);return blockIds.get(n); }
      function adjacentText(e) { const parts=[];for(let n=e?.nextSibling;n;n=n.nextSibling){if(n.nodeType===Node.TEXT_NODE){parts.push(n.textContent||'');continue;}if(n.nodeType===Node.COMMENT_NODE)continue;break;}return clean(parts.join(' ')); }
      function namedPanel(e) { const tags=new Set(['H1','H2','H3','H4','H5','H6','DT','LEGEND']);for(let n=e?.parentElement,d=0;n&&n!==document.body&&d<5;n=n.parentElement,d++){for(const h of n.children){if(!tags.has(h.tagName)&&String(h.getAttribute('role')||'').toLowerCase()!=='tab')continue;const x=normLabel(h.textContent);if(x.length<=40&&![...x].some(c=>'，,。；;！？!?'.includes(c))&&[...extras].some(label=>x.includes(label)))return true;}}return false; }

      const evidence=[],seen=new Set();
      function add(v, method, strength, e, raw, label='', source='') { if(strength!=='strong'&&clean(v).includes('\n'))return false;if(e&&(!label||normLabel(label)==='地址')&&excludedContext(e))return false;const address=cleanAddress(v,label),key=address.replace(/\s+/g,'');if(isLabel(address)||!looks(address,strength)||seen.has(key))return false;seen.add(key);const c=e?context(e):{before:[],after:[]};evidence.push({id:`address_${evidence.length+1}`,address_text:address,raw_text:clean(raw||v),label_text:clean(label),extraction_method:method,evidence_strength:strength,source_region:source||(e?region(e):'structured_data'),block_id:e?block(e):'',dom_order:e?(order.get(e)??-1):-1,visible:e?visible(e):false,context_before:c.before,context_after:c.after});return true; }
      function structured(v){if(typeof v==='string')return cleanAddress(v);if(!v||typeof v!=='object')return '';const parts=[];for(const k of ['addressRegion','addressLocality','addressDistrict','streetAddress']){const x=clean(v[k]).replace(/\n/g,' ');if(x&&!parts.some(p=>p===x||p.includes(x)))parts.push(x);}return parts.join('');}
      function visit(v){if(!v||typeof v!=='object')return;if(Array.isArray(v)){v.forEach(visit);return;}const types=Array.isArray(v['@type'])?v['@type']:[v['@type']];if(types.some(t=>String(t||'').toLowerCase()==='postaladdress')){const x=structured(v);add(x,'structured_data','strong',null,x,'','structured_data');}if(v.address){const x=structured(v.address);add(x,'structured_data','strong',null,x,'','structured_data');}Object.values(v).forEach(visit);}
      for(const s of document.querySelectorAll('script[type="application/ld+json"]')){try{visit(JSON.parse(s.textContent));}catch{}}
      function related(e){if(e.tagName==='DT'&&e.nextElementSibling?.tagName==='DD')return e.nextElementSibling;const row=e.closest('tr');if(row){const cells=[...row.children],cell=e.closest('th,td'),i=cells.indexOf(cell);if(i>=0&&cells[i+1])return cells[i+1];}return e.nextElementSibling;}
      for(const e of elements){
        const x=text(e);
        if(!x||x.length>500||!isLabel(x))continue;
        let v=related(e),value=v?text(v):adjacentText(e);
        if(!v&&value)v=e.parentElement;
        if(!v||region(e)==='body'&&(!visible(e)||!visible(v))&&!namedPanel(v))continue;
        const nestedElement=[...v.querySelectorAll('*')].find(
          c=>inline(text(c))&&![...c.children].some(k=>inline(text(k)))
        );
        const nested=inline(text(nestedElement||v));
        const label=nested&&normLabel(nested.label)!=='地址'?nested.label:x;
        const leaves=[...v.querySelectorAll('*')].filter(
          c=>looks(text(c),'medium')&&![...c.children].some(k=>looks(text(k),'medium'))
        );
        if(leaves.length<2&&(nested||looks(value,'medium'))){
          add(nested?nested.value:value,'label_relation','strong',
              nestedElement||v,`${x}\n${value}`,label);
        }
      }
      for(const e of elements){
        const x=text(e);
        if(!x||x.length>500)continue;
        if(region(e)==='body'&&((!visible(e)&&!namedPanel(e))||x.length>200))continue;
        const matches=inlines(x);
        if(!matches.length)continue;
        let ownsInline=false;
        for(const match of matches){
          if(richerInlineAncestor(e,match)||inlineOwnedByChild(e,match))continue;
          ownsInline=true;
          add(match.value,'inline_label','strong',e,x,match.label);
        }
        if(ownsInline&&region(e)!=='body'){
          let followsAddress=false;
          const innerLines=clean(x).split('\n');
          const sourceLines=clean(e.textContent).split('\n');
          const lines=sourceLines.length>innerLines.length?sourceLines:innerLines;
          for(const line of lines){
            if(inline(line)){followsAddress=true;continue;}
            if(followsAddress&&line.split(admin).length>2){
              add(line,'inline_continuation','strong',e,line);
            }
          }
        }
      }
      for(const e of elements){
        const x=text(e),label=configuredSuffix(x);
        if(!label||!visible(e)||x.length>160||!looks(x,'medium'))continue;
        if([...e.children].filter(c=>looks(text(c),'medium')).length>1)continue;
        if(add(x,'configured_suffix','medium',e,x)){
          evidence[evidence.length-1].label_text=label;
        }
      }
      const roots=elements.filter(e=>e.tagName==='FOOTER'||String(e.getAttribute('role')||'').toLowerCase()==='contentinfo'||/(?:^|[ _-])(?:footer|foot|bottom|bot|copyright)(?:$|[ _-])/.test(hint(e))).filter((e,i,a)=>!a.some((r,j)=>j<i&&r.contains(e)));
      for(const root of roots){const named=root.querySelector('[class*="location" i],[id*="location" i],[class*="address" i],[id*="address" i]');if(!contact.test(text(root))&&!named)continue;const list=[root,...root.querySelectorAll('*')].filter(e=>!excluded.has(e.tagName)).sort((a,b)=>text(a).length-text(b).length);for(const e of list){const x=text(e);if(!x||isLabel(x)||inline(x)||/^[^：:\n]{1,12}[：:]/.test(x))continue;const lines=x.split('\n');if(lines.length>1){let added=false;for(const line of lines){if(!line||isLabel(line)||inline(line)||/^[^：:\n]{1,12}[：:]/.test(line))continue;if(add(line,'footer_contact','medium',e,line))added=true;}if(added)continue;}const child=[...e.children].some(c=>looks(text(c),'medium'));if(!child)add(x,'footer_contact','medium',e,x);}}
      const consolidated=evidence.filter((item,index)=>!evidence.some((other,otherIndex)=>
        otherIndex!==index
        &&other.block_id===item.block_id
        &&normLabel(other.label_text)===normLabel(item.label_text)
        &&other.address_text.length>item.address_text.length
        &&other.address_text.startsWith(item.address_text)
      ));
      const links=[...document.querySelectorAll('a[href]')].map(e=>({text:text(e).slice(0,120),url:e.href}));
      return {address_evidence:consolidated,addressNodes:consolidated,links};
    }
    """, labels)


def build_page_result(requested_url, domains, **values):
    """生成字段稳定的通用官网抓取结果。"""
    result = {'stage': 'official_page_address_evidence',
              'requested_url': requested_url, 'final_url': '', 'http_status': None,
              'page_status': 'error', 'title': '', 'official_domains': domains,
              'address_evidence': [], 'links': [], 'warnings': []}
    result['access_attempts'] = []
    result.update(values)
    return result


class OfficialPageFetcher:
    """复用 Chromium，并为每所学校建立隔离浏览器上下文。"""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self._domain_preferences = {}

    def __enter__(self):
        self.playwright = sync_playwright().start()
        try:
            # 优先使用本机 Chrome，减少中国站点对内置 Chromium 指纹的误判。
            self.browser = self.playwright.chromium.launch(
                channel='chrome', headless=True, args=CHROME_ARGS,
            )
        except Exception:
            # 没有 Chrome 通道时回退到 Playwright 自带 Chromium。
            try:
                self.browser = self.playwright.chromium.launch(
                    headless=True, args=CHROME_ARGS,
                )
            except Exception:
                self.playwright.stop()
                self.playwright = None
                raise
        return self

    def new_context(self):
        """创建固定指纹的浏览器上下文。"""
        return self.browser.new_context(
            user_agent=USER_AGENT,
            extra_http_headers=BROWSER_HEADERS,
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )

    def __exit__(self, exc_type, exc_value, traceback):
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None

    def fetch(self, url, official_domains, extra_address_labels=(),
              context=None, page=None):
        """实时抓取一个官方页面，并在返回前关闭该页的独立上下文。"""
        if self.browser is None:
            raise RuntimeError('OfficialPageFetcher 必须在 with 语句中使用')
        domains = sorted({
            item for item in map(normalize_domain, official_domains) if item
        })
        if not domains or not is_url_in_domains(url, domains):
            raise ValueError('请求 URL 或官方域名无效')
        owns_context = context is None
        context = context or self.new_context()
        try:
            page = page or context.new_page()
            access_attempts = []
            try:
                started = time.monotonic()
                try:
                    response = fetch_browser_page(page, url)
                    if response is not None and response.status >= 400:
                        raise RuntimeError(f'页面返回 HTTP {response.status}')
                    access_attempts.append({
                        'method': 'playwright', 'url': url,
                        'final_url': page.url, 'http_status': response.status if response else None,
                        'success': True, 'error': '',
                        'elapsed_ms': round((time.monotonic() - started) * 1000),
                    })
                except Exception as browser_error:
                    browser_status = getattr(locals().get('response'), 'status', None)
                    access_attempts.append({
                        'method': 'playwright', 'url': url, 'final_url': page.url,
                        'http_status': browser_status, 'success': False,
                        'error': format_page_error(browser_error),
                        'elapsed_ms': round((time.monotonic() - started) * 1000),
                    })
                    started = time.monotonic()
                    try:
                        host = (urlparse(url).hostname or '').lower().rstrip('.')
                        preferred_method = (
                            self._domain_preferences.get(host)
                            if browser_status not in {403, 404}
                            else 'curl'
                        )
                        response = fetch_http_page(
                            page, url, preferred_method=preferred_method,
                        )
                        direct_attempts = getattr(response, 'access_attempts', ())
                        if direct_attempts:
                            access_attempts.extend(direct_attempts)
                        else:
                            access_attempts.append({
                                'method': 'urllib_or_curl', 'url': url,
                                'final_url': response.url, 'http_status': response.status,
                                'success': True, 'error': '',
                                'elapsed_ms': round((time.monotonic() - started) * 1000),
                            })
                        successful_direct = next(
                            (item for item in reversed(access_attempts)
                             if item.get('success') and item.get('method') in {'urllib', 'curl'}),
                            None,
                        )
                        if successful_direct is not None:
                            self._domain_preferences[host] = successful_direct['method']
                    except Exception as http_error:
                        access_attempts.append({
                            'method': 'urllib_or_curl', 'url': url,
                            'final_url': '', 'http_status': None, 'success': False,
                            'error': format_page_error(http_error),
                            'elapsed_ms': round((time.monotonic() - started) * 1000),
                        })
                        raise browser_error
                status = response.status if response else None
                resolved_url = response.url or page.url
                if not is_url_in_domains(resolved_url, domains):
                    raise ValueError(f'跳转后的最终 URL 不属于已确认的官方域名：{resolved_url}')
                if status is not None and status >= 400:
                    return build_page_result(url, domains, final_url=resolved_url,
                        http_status=status, page_status='http_error', title=page.title(),
                        access_attempts=access_attempts,
                        warnings=[f'页面返回 HTTP {status}'])
                page.wait_for_timeout(800)
                data = collect_official_page_data(page, extra_address_labels)
                if not data['address_evidence']:
                    page.wait_for_timeout(1500)
                    data = collect_official_page_data(page, extra_address_labels)
                warnings = [] if data['address_evidence'] else ['未发现可靠地址证据']
                return build_page_result(url, domains, final_url=resolved_url,
                    http_status=status, page_status='ok', title=page.title(),
                    address_evidence=data['address_evidence'], links=data['links'],
                    access_attempts=access_attempts,
                    warnings=warnings)
            except Exception as error:
                return build_page_result(
                    url, domains, access_attempts=access_attempts,
                    warnings=[format_page_error(error)],
                )
        finally:
            if owns_context:
                context.close()

    def fetch_pages(self, page_requests, extra_address_labels=()):
        """顺序抓取同一学校的多页，复用一个 context 和 page。"""
        if self.browser is None:
            raise RuntimeError('OfficialPageFetcher 必须在 with 语句中使用')
        context = self.new_context()
        try:
            page = context.new_page()
            return [self.fetch(
                request['url'],
                request['official_domains'],
                extra_address_labels=extra_address_labels,
                context=context,
                page=page,
            ) for request in page_requests]
        finally:
            context.close()


def fetch_official_page(url, official_domains, extra_address_labels=()):
    """抓取单个官方页面并返回通用地址证据。"""
    with OfficialPageFetcher() as fetcher:
        return fetcher.fetch(
            url, official_domains,
            extra_address_labels=extra_address_labels,
        )
