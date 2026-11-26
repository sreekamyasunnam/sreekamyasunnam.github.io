#!/usr/bin/env python3
"""Build DE/FR/IT versions of the portfolio from the English source.
English index.html and capstone/index.html are the source of truth.
Usage: python3 build.py /path/to/repo
"""
import re, sys, json, html, os

REPO = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
LANGS = ['de', 'fr', 'it']
SITE = 'https://sreekamyasunnam.github.io'
CV = {l: 'Sree_Kamya_Sunnam_CV.pdf' for l in ['en','de','fr','it']}

keys = json.load(open(os.path.join(HERE, 'keys.json')))
norm = lambda s: re.sub(r'\s+', ' ', s).strip()

def load(lang):
    d = {}
    for line in open(os.path.join(HERE, f'{lang}.txt'), encoding='utf-8'):
        line = line.rstrip('\n')
        if not line or '|' not in line: continue
        i, t = line.split('|', 1)
        d[norm(keys[int(i)])] = t
    return d

# ---------- protection of base64 blobs ----------
def protect(h):
    blobs = []
    def sub(m):
        blobs.append(m.group(0)); return f'\x00B{len(blobs)-1}\x00'
    h = re.sub(r'data:[a-zA-Z/+.-]+;base64,[A-Za-z0-9+/=]+', sub, h)
    return h, blobs

def restore(h, blobs):
    return re.sub(r'\x00B(\d+)\x00', lambda m: blobs[int(m.group(1))], h)

# ---------- translation of markup text ----------
def tr_text(seg, D, stats):
    if not seg.strip(): return seg
    k = norm(html.unescape(seg))
    if k in D:
        stats['hit'] += 1
        lead = re.match(r'\s*', seg).group(0); trail = re.search(r'\s*$', seg).group(0)
        return lead + html.escape(D[k], quote=False) + trail
    return seg

ATTRS = ('placeholder', 'title', 'alt', 'aria-label', 'content')
def tr_tag(tag, D, stats):
    def sub(m):
        name, q, val = m.group(1), m.group(2), m.group(3)
        k = norm(html.unescape(val))
        if k in D:
            stats['hit'] += 1
            return f'{name}={q}{html.escape(D[k], quote=True)}{q}'
        return m.group(0)
    return re.sub(r'\b(' + '|'.join(ATTRS) + r')=(["\'])(.*?)\2', sub, tag, flags=re.S)

def tr_markup(h, D, stats, js=False):
    out = []
    pos = 0
    pat = re.compile(r'<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<!--.*?-->|<[^>]*>', re.S | re.I)
    for m in pat.finditer(h):
        out.append(tr_text(h[pos:m.start()], D, stats))
        t = m.group(0)
        if t.lower().startswith('<script'):
            o = re.match(r'<script\b[^>]*>', t, re.I).group(0)
            body = t[len(o):-len('</script>')]
            if 'application/ld+json' in o: out.append(t)
            else: out.append(o + tr_js(body, D, stats) + '</script>')
        elif t.lower().startswith('<style') or t.startswith('<!--'):
            out.append(t)
        else:
            out.append(tr_tag(t, D, stats))
        pos = m.end()
    out.append(tr_text(h[pos:], D, stats))
    return ''.join(out)

# ---------- translation of JS string literals ----------
def js_unescape(s, q):
    return s.replace('\\' + q, q).replace("\\n", "\n").replace('\\\\', '\\')

def js_escape(s, q):
    s = s.replace('\\', '\\\\').replace(q, '\\' + q)
    if q == '`': s = s.replace('${', '\\${')
    return s

def tr_js(code, D, stats):
    out = []; i = 0; n = len(code)
    prev_sig = ''
    while i < n:
        c = code[i]
        if code.startswith('//', i):
            j = code.find('\n', i); j = n if j < 0 else j
            out.append(code[i:j]); i = j; continue
        if code.startswith('/*', i):
            j = code.find('*/', i + 2); j = n if j < 0 else j + 2
            out.append(code[i:j]); i = j; continue
        if c == '/' and prev_sig and prev_sig in '(,=:[!&|?{};+-*%<>~^' :
            # regex literal
            j = i + 1; cls = False
            while j < n:
                if code[j] == '\\': j += 2; continue
                if code[j] == '[': cls = True
                elif code[j] == ']': cls = False
                elif code[j] == '/' and not cls: break
                elif code[j] == '\n': break
                j += 1
            out.append(code[i:j + 1]); i = j + 1; prev_sig = '/'; continue
        if c in '"\'`':
            q = c; j = i + 1; depth = 0
            while j < n:
                if code[j] == '\\': j += 2; continue
                if q == '`' and code.startswith('${', j): depth += 1; j += 2; continue
                if q == '`' and depth and code[j] == '}': depth -= 1; j += 1; continue
                if code[j] == q and not depth: break
                j += 1
            raw = code[i + 1:j]
            val = js_unescape(raw, q)
            k = norm(val)
            if k in D and (q != '`' or '${' not in raw):
                stats['hit'] += 1
                out.append(q + js_escape(D[k], q) + q)
            elif '<' in raw and '>' in raw:
                out.append(q + tr_inner_markup(raw, D, stats, q) + q)
            else:
                out.append(code[i:j + 1])
            i = j + 1; prev_sig = 'x'; continue
        out.append(c)
        if not c.isspace(): prev_sig = c
        i += 1
    return ''.join(out)

def tr_inner_markup(raw, D, stats, q):
    # translate text between tags inside a JS string (escaping kept simple)
    parts = re.split(r'(<[^>]*>)', raw)
    res = []
    for p in parts:
        if p.startswith('<'):
            res.append(tr_tag(p, D, stats))
        elif p.strip() and '${' not in p:
            k = norm(html.unescape(p.replace("\\'", "'").replace('\\"', '"')))
            if k in D:
                stats['hit'] += 1
                lead = re.match(r'\s*', p).group(0); trail = re.search(r'\s*$', p).group(0)
                res.append(lead + html.escape(D[k], quote=True) + trail)
            else: res.append(p)
        else: res.append(p)
    return ''.join(res)

# ---------- language UI ----------
UI = {
 'en': {'lead': 'Reading in English', 'q': 'Another language?', 'note': ''},
 'de': {'lead': 'Sie lesen auf Deutsch', 'q': 'Andere Sprache?', 'note': 'Übersetzte Seite · Ich arbeite auf Englisch und lerne fleissig Deutsch (A1).'},
 'fr': {'lead': 'Vous lisez en français', 'q': 'Une autre langue ?', 'note': "Page traduite · Je travaille en anglais et j'apprends activement le français (A1)."},
 'it': {'lead': 'Sta leggendo in italiano', 'q': "Un'altra lingua?", 'note': "Pagina tradotta · La mia lingua di lavoro è l'inglese."},
}
NAMES = {'en': 'English', 'de': 'Deutsch', 'fr': 'Français', 'it': 'Italiano'}

def head_block(lang, page):
    path = '' if page == 'home' else 'capstone/'
    alts = ''.join(f'<link rel="alternate" hreflang="{l}" href="{SITE}/{"" if l=="en" else l+"/"}{path}">' for l in ['en'] + LANGS)
    alts += f'<link rel="alternate" hreflang="x-default" href="{SITE}/{path}">'
    js = """<script>(function(){var C='%s',P='%s',L=null;window.__skC=C;window.__skP=P;try{L=localStorage.getItem('sk_lang')}catch(e){}
window.__skUrl=function(l){var up=(C==='en'?'':'../')+(P==='home'?'':'../');return up+(l==='en'?'':l+'/')+(P==='home'?'index.html':'capstone/index.html')};
if(C==='en'&&/^(de|fr|it)$/.test(L||'')){location.replace(window.__skUrl(L)+location.hash);return}
window.__skGate=(C==='en'&&P==='home'&&!L);})();</script>""" % (lang, page)
    return '<!--I18N-HEAD-->' + alts + js + '<!--/I18N-HEAD-->'

CSS = """<style>
.sk-lb{margin-right:auto;display:flex;align-items:center;gap:12px;font-family:'DM Sans',sans-serif;color:#4A3520;font-size:12.5px;line-height:1.25}
.sk-lb .sk-t{display:flex;flex-direction:column}
.sk-lb .sk-lead{letter-spacing:.02em}.sk-lb .sk-sep{font-style:normal}.sk-lb .sk-lead b{font-weight:500;color:#1E0E04}
.sk-lb .sk-note{font-size:11px;font-style:italic;color:#7A5612;margin-top:2px}
.sk-pills{display:flex;gap:5px}
.sk-pill{font-size:11px;font-weight:500;letter-spacing:.08em;padding:3px 7px;border-radius:999px;border:1px solid #B8963E;color:#7A5612;text-decoration:none;cursor:none;transition:all .25s ease;background:rgba(242,234,216,.6)}
.sk-pill:hover{background:#B8963E;color:#FFF8EC}
.sk-pill.on{background:#1E0E04;border-color:#1E0E04;color:#F2EAD8}
@media(max-width:768px){.sk-lb .sk-lead b,.sk-lb .sk-sep,.sk-lb .sk-note{display:none}.sk-lb{gap:8px;font-size:12px}.sk-pill{padding:3px 6px;font-size:10.5px}}
#skGate{position:fixed;inset:0;z-index:99990;background:#F2EAD8;display:flex;align-items:center;justify-content:center;padding:24px;opacity:1;transition:opacity .6s ease;overflow:auto}
#skGate.out{opacity:0;pointer-events:none}
.skg-in{max-width:880px;width:100%;text-align:center;animation:skgUp .9s ease both}
@keyframes skgUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
.skg-hello{font-size:12px;letter-spacing:.32em;text-transform:uppercase;color:#8B6414;margin-bottom:22px}
.skg-h{font-family:'Playfair Display',serif;font-size:clamp(34px,5.4vw,58px);line-height:1.08;color:#1E0E04;margin:0}
.skg-h em{display:block;font-style:italic;font-weight:400;color:#B8963E;font-size:.62em;margin-top:12px}
.skg-sub{font-size:15px;color:#4A3520;margin:18px auto 34px;max-width:520px}
.skg-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.skg-c{background:#FAF4E6;border:1px solid #D9C9A6;border-radius:14px;padding:22px 14px 20px;cursor:none;text-decoration:none;color:#1E0E04;transition:transform .3s ease,border-color .3s ease,box-shadow .3s ease}
.skg-c:hover{transform:translateY(-4px);border-color:#B8963E;box-shadow:0 10px 28px rgba(122,86,18,.12)}
.skg-code{font-size:11px;letter-spacing:.2em;color:#B8963E;font-weight:500}
.skg-n{font-family:'Playfair Display',serif;font-size:24px;margin:6px 0 8px}
.skg-d{font-size:13px;color:#4A3520;line-height:1.45}
.skg-f{font-size:12.5px;color:#7A5612;margin-top:28px}
@media(max-width:768px){.skg-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.skg-c{padding:16px 10px}.skg-n{font-size:20px}.skg-d{font-size:12px}.skg-sub{margin-bottom:24px}}
</style>"""

def bar_html(lang):
    u = UI[lang]
    pills = ''.join(f'<a class="sk-pill{" on" if l==lang else ""}" data-l="{l}" href="#" title="{NAMES[l]}" aria-label="{NAMES[l]}">{l.upper()}</a>' for l in ['en'] + LANGS)
    note = f'<span class="sk-note">{html.escape(u["note"])}</span>' if u['note'] else ''
    return (f'<div class="sk-lb" translate="no"><span class="sk-t"><span class="sk-lead"><b>{html.escape(u["lead"])}</b><i class="sk-sep"> · </i><span class="sk-q">{html.escape(u["q"])}</span></span>{note}</span>'
            f'<span class="sk-pills">{pills}</span></div>')

GATE = """<div id="skGate" style="display:none" translate="no" role="dialog" aria-label="Choose a language"><div class="skg-in">
<div class="skg-hello">Hello · Grüezi · Bonjour · Ciao</div>
<h1 class="skg-h">I speak data fluently.<em>Which language would you like to read me in?</em></h1>
<p class="skg-sub">Same story, same numbers, your language. Pick one and let's begin.</p>
<div class="skg-grid">
<a class="skg-c" href="#" data-l="en"><div class="skg-code">EN</div><div class="skg-n">English</div><div class="skg-d">My working language. Straight to the point.</div></a>
<a class="skg-c" href="#" data-l="de"><div class="skg-code">DE</div><div class="skg-n">Deutsch</div><div class="skg-d">Präzise wie ein Schweizer Uhrwerk.</div></a>
<a class="skg-c" href="#" data-l="fr"><div class="skg-code">FR</div><div class="skg-n">Français</div><div class="skg-d">Tout droit des rives du Léman.</div></a>
<a class="skg-c" href="#" data-l="it"><div class="skg-code">IT</div><div class="skg-n">Italiano</div><div class="skg-d">Con un pizzico di dolce vita.</div></a>
</div>
<div class="skg-f">You can switch anytime from the top of the page.</div>
</div></div>"""

SWITCH_JS = """<script>(function(){
function go(l){try{localStorage.setItem('sk_lang',l)}catch(e){}
location.href=window.__skUrl(l)+location.hash;}
document.querySelectorAll('.sk-pill').forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();if(a.classList.contains('on'))return;go(a.dataset.l)})});
var g=document.getElementById('skGate');
if(g&&window.__skGate){g.style.display='flex';document.documentElement.style.overflow='hidden';
g.querySelectorAll('.skg-c').forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();var l=a.dataset.l;
if(l!=='en'){go(l);return}
try{localStorage.setItem('sk_lang','en')}catch(x){}
g.classList.add('out');document.documentElement.style.overflow='';setTimeout(function(){g.remove()},650);
if(typeof playHero==='function'){['ghostTxt','heroPic','veveyCard'].forEach(function(id){var el=document.getElementById(id);el&&el.classList.remove('on')});
document.querySelectorAll('.h-el').forEach(function(el){el.classList.remove('on')});
var s=document.getElementById('statsBar');s&&s.classList.remove('bg-on','text-on');setTimeout(playHero,150);}
})});}
})();</script>"""

def strip_blocks(h):
    for tag in ['I18N-HEAD', 'I18N-CSS', 'I18N-BAR', 'I18N-GATE', 'I18N-JS']:
        h = re.sub(rf'<!--{tag}-->.*?<!--/{tag}-->', '', h, flags=re.S)
    return h

def inject(h, lang, page):
    h = strip_blocks(h)
    h = re.sub(r'<html lang="[a-z]+"', f'<html lang="{lang}"', h, count=1)
    h = h.replace('</head>', head_block(lang, page) + '<!--I18N-CSS-->' + CSS + '<!--/I18N-CSS-->\n</head>', 1)
    if page == 'home':
        h = h.replace('<nav id="navbar">', '<nav id="navbar">\n  <!--I18N-BAR-->' + bar_html(lang) + '<!--/I18N-BAR-->', 1)
        gate = GATE if lang == 'en' else ''
        h = re.sub(r'(<body[^>]*>)', lambda m: m.group(1) + '\n<!--I18N-GATE-->' + gate + '<!--/I18N-GATE-->', h, count=1)
    else:
        capbar = ('<div style="position:fixed;top:14px;right:18px;z-index:50;background:rgba(242,234,216,.92);padding:6px 10px;border-radius:999px;border:1px solid #D9C9A6">'
                  + bar_html(lang).replace('class="sk-lb"', 'class="sk-lb" style="margin:0"') + '</div>')
        h = re.sub(r'(<body[^>]*>)', lambda m: m.group(1) + '\n<!--I18N-BAR-->' + capbar + '<!--/I18N-BAR-->', h, count=1)
    h = h.replace('</body>', '<!--I18N-JS-->' + SWITCH_JS + '<!--/I18N-JS-->\n</body>', 1)
    return h

def localise_paths(h, lang, page):
    if lang == 'en': return h
    up = '../' if page == 'home' else '../../'
    h = re.sub(r'(?<=[\s"\'(,])(images|cv)/', lambda m: up + m.group(1) + '/', h)
    h = h.replace(f'content="{SITE}/"', f'content="{SITE}/{lang}/"')
    h = h.replace(f'content="{SITE}/capstone/"', f'content="{SITE}/{lang}/capstone/"')
    h = h.replace(f'href="{SITE}/#projects"', f'href="{SITE}/{lang}/#projects"')
    return h

def set_cv(h, lang):
    return re.sub(r'href="((?:\.\./)*)cv/[^"]+\.pdf" download="[^"]+"',
                  lambda m: f'href="{m.group(1)}cv/{CV[lang]}" download="{CV[lang]}"', h)

def build(src_path, page, out_paths):
    src = open(src_path, encoding='utf-8').read()
    src = strip_blocks(src)
    # English: just inject UI
    en = set_cv(inject(src, 'en', page), 'en')
    open(src_path, 'w', encoding='utf-8').write(en)
    for lang in LANGS:
        D = load(lang)
        p, blobs = protect(src)
        stats = {'hit': 0}
        t = tr_markup(p, D, stats)
        t = restore(t, blobs)
        t = inject(t, lang, page)
        t = localise_paths(t, lang, page)
        t = set_cv(t, lang)
        os.makedirs(os.path.dirname(out_paths[lang]), exist_ok=True)
        open(out_paths[lang], 'w', encoding='utf-8').write(t)
        print(page, lang, 'replacements:', stats['hit'])

build(os.path.join(REPO, 'index.html'), 'home', {l: os.path.join(REPO, l, 'index.html') for l in LANGS})
build(os.path.join(REPO, 'capstone', 'index.html'), 'capstone', {l: os.path.join(REPO, l, 'capstone', 'index.html') for l in LANGS})
