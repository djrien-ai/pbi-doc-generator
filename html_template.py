import os

CSS_STYLES = r"""
/* ── CSS Variables ─────────────────────────────────────────────── */
:root {
    --bg: #ffffff;
    --fg: #1f2328;
    --fg-muted: #636c76;
    --border: #d1d9e0;
    --border-light: #e8ecf0;
    --accent: #0969da;
    --accent-hover: #0550ae;
    --code-bg: #f6f8fa;
    --table-stripe: #f6f8fa;
    --note-bg: #ddf4ff; --note-border: #54aeff; --note-fg: #0969da;
    --tip-bg: #dafbe1; --tip-border: #4ac26b; --tip-fg: #1a7f37;
    --important-bg: #fbefff; --important-border: #a475f9; --important-fg: #8250df;
    --warning-bg: #fff8c5; --warning-border: #d4a72c; --warning-fg: #9a6700;
    --caution-bg: #ffebe9; --caution-border: #ff8182; --caution-fg: #d1242f;
    --sidebar-bg: #f6f8fa;
    --sidebar-width: 280px;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#0d1117; --fg:#e6edf3; --fg-muted:#8b949e;
    --border:#30363d; --border-light:#21262d;
    --accent:#4493f8; --accent-hover:#58a6ff;
    --code-bg:#161b22; --table-stripe:#161b22; --sidebar-bg:#0d1117;
    --note-bg:#0c2d4a; --tip-bg:#102a16; --important-bg:#241a3a;
    --warning-bg:#2d2410; --caution-bg:#3a1416;
  }
}
[data-theme="dark"] {
  --bg:#0d1117; --fg:#e6edf3; --fg-muted:#8b949e;
  --border:#30363d; --border-light:#21262d;
  --accent:#4493f8; --accent-hover:#58a6ff;
  --code-bg:#161b22; --table-stripe:#161b22; --sidebar-bg:#0d1117;
  --note-bg:#0c2d4a; --tip-bg:#102a16; --important-bg:#241a3a;
  --warning-bg:#2d2410; --caution-bg:#3a1416;
}

/* ── Reset ─────────────────────────────────────────────────────── */
* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

/* ── Body ──────────────────────────────────────────────────────── */
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: var(--fg);
    background: var(--bg);
}

/* ── Layout ────────────────────────────────────────────────────── */
.page-wrapper {
    display: flex;
    min-height: 100vh;
}

.dax-explanation {
    margin-top: -10px;
    margin-bottom: 16px;
    padding: 12px 16px;
    background-color: var(--note-bg);
    border-left: 4px solid var(--note-border);
    border-radius: 0 0 6px 6px;
    font-size: 13.5px;
    color: var(--fg);
}
.dax-explanation ul {
    margin-left: 20px;
    margin-top: 6px;
}

/* ── Sidebar ───────────────────────────────────────────────────── */
.sidebar {
    position: fixed;
    top: 0;
    left: 0;
    width: var(--sidebar-width);
    height: 100vh;
    overflow-y: auto;
    background: var(--sidebar-bg);
    border-right: 1px solid var(--border);
    padding: 20px 14px;
    font-size: 13px;
    z-index: 100;
}

.sidebar h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--fg-muted);
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}

.sidebar ul {
    list-style: none;
}

.sidebar .toc > li {
    margin-bottom: 4px;
}

.sidebar li a {
    display: block;
    padding: 4px 8px;
    border-radius: 6px;
    color: var(--fg);
    text-decoration: none;
    transition: background 0.15s;
}

.sidebar li a:hover {
    background: var(--border-light);
    color: var(--accent);
}

.sidebar li a.active {
    background: var(--note-bg);
    color: var(--accent);
    font-weight: 600;
}

.sidebar ul ul {
    padding-left: 14px;
}

.sidebar ul ul li a {
    font-size: 12px;
    color: var(--fg-muted);
    padding: 2px 8px;
}

.sidebar ul ul li a:hover {
    color: var(--accent);
}

/* ── Content ───────────────────────────────────────────────────── */
.content {
    margin-left: var(--sidebar-width);
    max-width: 960px;
    padding: 40px 48px 80px;
}

/* ── Back-to-top button ────────────────────────────────────────── */
.back-to-top {
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--accent);
    color: #fff;
    border: none;
    cursor: pointer;
    font-size: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.3s;
    z-index: 200;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.back-to-top.visible {
    opacity: 1;
}

.back-to-top:hover {
    background: var(--accent-hover);
}

/* ── Tables ────────────────────────────────────────────────────── */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0 24px;
    font-size: 14px;
    table-layout: auto;
}

th, td {
    padding: 10px 12px;
    border: 1px solid var(--border);
    text-align: left;
    word-break: normal;
}

th {
    background: var(--bg);
    color: var(--fg);
    font-weight: 600;
}

tr:nth-child(even) {
    background: var(--table-stripe);
}

/* ── Typography & Elements ─────────────────────────────────────── */
h1 { font-size: 28px; margin-bottom: 24px; font-weight: 600; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
h2 { font-size: 22px; margin: 32px 0 16px; font-weight: 600; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
h3 { font-size: 18px; margin: 24px 0 12px; font-weight: 600; }
h4 { font-size: 16px; margin: 20px 0 10px; font-weight: 600; }

code {
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    font-size: 13px;
    background: var(--code-bg);
    padding: 2px 5px;
    border-radius: 4px;
}

pre {
    background: var(--code-bg);
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 16px 0;
    border: 1px solid var(--border);
}

pre code {
    background: transparent;
    padding: 0;
    border-radius: 0;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.copy-btn {
    position: absolute;
    top: 8px;
    right: 8px;
    padding: 4px 8px;
    font-size: 12px;
    color: var(--fg-muted);
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.2s, color 0.2s, border-color 0.2s;
}
pre:hover .copy-btn { opacity: 1; }
.copy-btn:hover { color: var(--accent); border-color: var(--accent); }

.alert {
    padding: 16px;
    border-left: 4px solid;
    border-radius: 6px;
    margin: 16px 0;
}
.alert p { margin: 0; }
.alert-note { background: var(--note-bg); border-color: var(--note-border); color: var(--note-fg); }
.alert-tip { background: var(--tip-bg); border-color: var(--tip-border); color: var(--tip-fg); }
.alert-important { background: var(--important-bg); border-color: var(--important-border); color: var(--important-fg); }
.alert-warning { background: var(--warning-bg); border-color: var(--warning-border); color: var(--warning-fg); }
.alert-caution { background: var(--caution-bg); border-color: var(--caution-border); color: var(--caution-fg); }

/* SVG Wireframe CSS */
.page-wf { max-width:800px; display:block; margin:20px 0; border:1px solid var(--border); border-radius:8px; background:var(--code-bg); overflow:hidden; }
.wf-container { position:relative; width:100%; padding-top:56.25%; /* 16:9 aspect ratio */ }
.wf-svg { position:absolute; top:0; left:0; width:100%; height:100%; }
.wf-canvas { fill: var(--bg); stroke: var(--border); stroke-width:2; }
.wf-visual rect { fill: var(--accent); fill-opacity:.10; stroke: var(--accent); stroke-width:2; }
.wf-ctrl   rect { fill: var(--fg-muted); fill-opacity:.10; stroke: var(--fg-muted); stroke-width:2; }
.wf-bg     rect { fill: none; stroke: var(--border); stroke-width:1.5; stroke-dasharray:3 4; }
.wf-hidden rect { stroke-dasharray:8 6; opacity:.55; }
.wf-visual:hover rect, .wf-ctrl:hover rect { fill-opacity:.26; }
.wf-num   { fill: var(--fg-muted); font:12px sans-serif;
            paint-order:stroke; stroke:var(--code-bg); stroke-width:3px; stroke-linejoin:round; }
.wf-label { fill: var(--fg); font:14px sans-serif; pointer-events:none;
            paint-order:stroke; stroke:var(--code-bg); stroke-width:3px; stroke-linejoin:round; }
@media print { .page-wf { max-width:100%; } }

  /* Semantic Layer Controls */
  .layer-controls { font-family: sans-serif; font-size: 13px; margin-bottom: 8px; display: flex; gap: 15px; color: var(--fg); }
  .layer-controls label { cursor: pointer; display: flex; align-items: center; gap: 5px; user-select: none; }
  .hidden-layer { opacity: 0 !important; pointer-events: none !important; transition: opacity 0.2s ease-in-out; }
"""

JS_THEME_INIT = r"""
(function () {
    var saved = localStorage.getItem('pbidoc-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
})();
"""

JS_MERMAID_INIT = r"""
document.addEventListener("DOMContentLoaded", function () {
    if (typeof mermaid !== "undefined") {
        mermaid.initialize({ startOnLoad: true, theme: "neutral" });
    }
});
"""

JS_BACK_TO_TOP = r"""
(function () {
    var btn = document.getElementById("backToTop");
    if (!btn) return;
    window.addEventListener("scroll", function () {
        if (window.scrollY > 300) {
            btn.classList.add("visible");
        } else {
            btn.classList.remove("visible");
        }
    });
    btn.addEventListener("click", function () {
        window.scrollTo({ top: 0, behavior: "smooth" });
    });
})();
"""

JS_SCROLL_SPY = r"""
(function () {
    var links = document.querySelectorAll(".sidebar a[href^='#']");
    if (!links.length) return;

    var sections = [];
    links.forEach(function (link) {
        var id = link.getAttribute("href").slice(1);
        var el = document.getElementById(id);
        if (el) sections.push({ el: el, link: link });
    });

    function highlight() {
        var scrollY = window.scrollY + 40;
        var current = null;
        for (var i = 0; i < sections.length; i++) {
            if (sections[i].el.offsetTop <= scrollY) {
                current = sections[i];
            }
        }
        links.forEach(function (l) { l.classList.remove("active"); });
        if (current) {
            current.link.classList.add("active");
            let parentUl = current.link.closest('ul');
            if (parentUl && parentUl.parentElement.tagName === 'LI' && !parentUl.classList.contains('toc')) {
                parentUl.style.display = 'block';
                let toggle = parentUl.parentElement.querySelector('span.toggle-icon');
                if (toggle) toggle.innerHTML = '&#9650;';
            }
        }
    }

    window.addEventListener("scroll", highlight);
    highlight();
})();
"""

JS_COLLAPSIBLE = r"""
(function () {
    document.querySelectorAll('.sidebar .toc > li').forEach(li => {
      const ul = li.querySelector('ul');
      if (ul) {
        li.style.position = 'relative';
        const toggle = document.createElement('span');
        toggle.className = 'toggle-icon';
        toggle.innerHTML = '&#9660;';
        toggle.style.cssText = 'position:absolute; right:8px; top:8px; font-size:10px; cursor:pointer; color:var(--fg-muted); transition: transform 0.2s;';
        li.insertBefore(toggle, li.firstChild);
        ul.style.display = 'none';
        
        const toggleMenu = (e) => {
          e.preventDefault();
          const isClosed = ul.style.display === 'none';
          ul.style.display = isClosed ? 'block' : 'none';
          toggle.innerHTML = isClosed ? '&#9650;' : '&#9660;';
        };
        toggle.addEventListener('click', toggleMenu);
      }
    });
})();
"""

JS_SEARCH = r"""
(function () {
    const input = document.getElementById('toc-search');
    if (!input) return;
    const allLi = Array.from(document.querySelectorAll('.sidebar li'));
    input.addEventListener('input', () => {
        const q = input.value.toLowerCase().trim();
        if (!q) { 
            allLi.forEach(li => li.style.display = ''); 
            window.dispatchEvent(new Event('scroll')); // trigger scroll to reset collapsible state
            return; 
        }
        allLi.forEach(li => li.style.display = 'none');
        allLi.forEach(li => {
            const a = li.querySelector(':scope > a');
            if (a && a.textContent.toLowerCase().includes(q)) {
                li.style.display = '';
                let p = li.parentElement;
                while (p && !p.classList.contains('sidebar')) {
                    if (p.tagName === 'LI') p.style.display = '';
                    if (p.tagName === 'UL' && !p.classList.contains('toc')) {
                        p.style.display = 'block';
                        let toggle = p.parentElement.querySelector('span.toggle-icon');
                        if (toggle) toggle.innerHTML = '&#9650;';
                    }
                    p = p.parentElement;
                }
            }
        });
    });
    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); input.focus(); }
    });
})();
"""

JS_COPY_BUTTONS = r"""
(function () {
    document.querySelectorAll('pre').forEach(pre => {
      if (pre.classList.contains('mermaid')) return;
      pre.style.position = 'relative';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'copy-btn';
      btn.textContent = 'Copy';
      btn.addEventListener('click', () => {
        const code = pre.querySelector('code') || pre;
        navigator.clipboard.writeText(code.innerText).then(() => {
          btn.textContent = 'Copied';
          setTimeout(() => (btn.textContent = 'Copy'), 1500);
        });
      });
      pre.appendChild(btn);
    });
})();
"""

JS_THEME_TOGGLE = r"""
(function () {
    const KEY = 'pbidoc-theme';
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
        let cur = document.documentElement.getAttribute('data-theme');
        if (!cur) {
            cur = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        const next = cur === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem(KEY, next);
    });
})();
"""


JS_WIREFRAME_TOGGLES = r'''
(function () {
    document.querySelectorAll('.layer-toggle').forEach(function(checkbox) {
        checkbox.addEventListener('change', function(e) {
            var target = e.target.getAttribute('data-target');
            // Find the sibling SVG element to only toggle layers for THIS specific wireframe
            var controlsDiv = e.target.closest('.layer-controls');
            if (!controlsDiv) return;
            var svg = controlsDiv.nextElementSibling;
            if (svg && svg.tagName.toLowerCase() === 'svg') {
                svg.querySelectorAll('[data-layer="' + target + '"]').forEach(function(g) {
                    if (e.target.checked) {
                        g.classList.remove('hidden-layer');
                    } else {
                        g.classList.add('hidden-layer');
                    }
                });
            }
        });
    });
})();
'''


JS_AI_IMPORTER = r"""
(function () {
    const importBtn = document.getElementById('ai-import-btn');
    const importPanel = document.getElementById('ai-import-panel');
    const applyBtn = document.getElementById('ai-apply-btn');
    const exportBtn = document.getElementById('ai-export-btn');
    const textarea = document.getElementById('ai-json-input');
    
    if (!importBtn) return;
    
    importBtn.addEventListener('click', () => {
        importPanel.style.display = importPanel.style.display === 'none' ? 'block' : 'none';
    });
    
    applyBtn.addEventListener('click', () => {
        const text = textarea.value;
        const match = text.match(/\[\s*\{.*?\}\s*\]/s);
        if (!match) {
            alert("Could not find a valid JSON array in the input.");
            return;
        }
        try {
            const data = JSON.parse(match[0]);
            let count = 0;
            data.forEach(item => {
                if (item.schema_version !== "1") return;
                const type = item.object_type;
                const name = item.object_name;
                const tbl = item.table;
                const definition = item.definition;
                const logic = item.business_logic;
                
                // Find node (case-insensitive where possible using i flag)
                let selector = `[data-object-type="${type}" i][data-object-name="${name}" i]`;
                if (tbl) selector += `[data-table="${tbl}" i]`;
                
                const nodes = document.querySelectorAll(selector);
                nodes.forEach(node => {
                    // Check if already injected
                    let existing = node.querySelector('.ai-enrichment-block');
                    if (!existing) {
                        // Create block depending on node type
                        existing = document.createElement('div');
                        existing.className = 'ai-enrichment-block alert alert-important';
                        existing.style.marginTop = '10px';
                        if (node.tagName === 'TR') {
                            const td = document.createElement('td');
                            td.colSpan = node.children.length; // Span across columns
                            td.appendChild(existing);
                            
                            // Insert as a new row after this row
                            const nextRow = document.createElement('tr');
                            nextRow.className = 'ai-enrichment-row';
                            nextRow.appendChild(td);
                            node.parentNode.insertBefore(nextRow, node.nextSibling);
                        } else {
                            node.appendChild(existing);
                        }
                    }
                    
                    // Update content
                    existing.innerHTML = `<strong>🤖 AI Definition:</strong> ${definition}<br/><br/><strong>🧠 Business Logic:</strong> ${logic}`;
                    count++;
                });
            });
            
            if (count === 0) {
                alert(`Found ${data.length} definitions in JSON, but none could be matched to the report objects. Check casing or object types.`);
            } else if (count < data.length) {
                alert(`Successfully injected ${count} definitions.\nNote: ${data.length - count} definitions were skipped (could not match table/object name).`);
            } else {
                alert(`Successfully injected all ${count} definitions.`);
            }
            importPanel.style.display = 'none';
        } catch (e) {
            alert("Error parsing JSON: " + e.message);
        }
    });
    
    exportBtn.addEventListener('click', () => {
        const html = document.documentElement.outerHTML;
        const blob = new Blob(["<!DOCTYPE html>\\n" + html], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = document.title.replace(" — Data Documentation", "") + "_enriched.html";
        a.click();
        URL.revokeObjectURL(url);
    });
})();
"""

JS_AUTO_OPEN_DETAILS = r"""
(function () {
    function openTargetDetails() {
        if (!location.hash) return;
        const el = document.querySelector(location.hash);
        if (!el) return;
        let p = el;
        while (p) { if (p.tagName === 'DETAILS') p.open = true; p = p.parentElement; }
        el.scrollIntoView();
    }
    window.addEventListener('load', openTargetDetails);
    window.addEventListener('hashchange', openTargetDetails);
})();
"""

def generate_html(report_name: str, sections_html: str, sidebar_html: str, metadata_html: str = "", enable_ai_enrichment: bool = False) -> str:
    from mermaid_js import MERMAID_JS
    
    # We will build the HTML by concatenating normal strings rather than running `.format()` on the entire document body.
    # We still use f-strings for the HTML parts, but carefully excluding CSS/JS blocks from the f-string interpolation.

    html_parts = []
    
    html_parts.append(f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report_name} — Data Documentation</title>
''')
    
    # Mermaid JS
    html_parts.append('<script>\n')
    html_parts.append(MERMAID_JS)
    html_parts.append('\n</script>\n')
    
    # Styles
    html_parts.append('<style>\n')
    html_parts.append(CSS_STYLES)
    html_parts.append('\n</style>\n')
    
    # Early JS
    html_parts.append('<script>\n')
    html_parts.append(JS_THEME_INIT)
    html_parts.append('\n</script>\n')
    
    # Body start
    import extract
    version_str = extract.__version__
    
    ai_overlay = ""
    if enable_ai_enrichment:
        ai_overlay = '''
<div style="position: fixed; bottom: 24px; left: 24px; z-index: 200;">
    <button id="ai-import-btn" style="background: var(--important-border); color: var(--important-fg); border: 2px solid var(--important-border); padding: 10px 16px; border-radius: 20px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">✨ Import AI Definitions</button>
</div>
<div id="ai-import-panel" style="display: none; position: fixed; bottom: 80px; left: 24px; width: 400px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.2); z-index: 200; padding: 16px;">
    <h3 style="margin-top: 0;">Import Prompt-Pack Output</h3>
    <p style="font-size: 13px; color: var(--fg-muted);">Paste the JSON array generated by the AI here:</p>
    <textarea id="ai-json-input" style="width: 100%; height: 200px; margin-bottom: 12px; font-family: monospace; font-size: 12px; padding: 8px; background: var(--code-bg); color: var(--fg); border: 1px solid var(--border); border-radius: 4px;"></textarea>
    <div style="display: flex; gap: 8px;">
        <button id="ai-apply-btn" style="flex: 1; background: var(--accent); color: #fff; border: none; padding: 8px; border-radius: 4px; font-weight: bold; cursor: pointer;">Inject Definitions</button>
        <button id="ai-export-btn" style="flex: 1; background: var(--success, #2ea043); color: #fff; border: none; padding: 8px; border-radius: 4px; font-weight: bold; cursor: pointer;">Export Enriched HTML</button>
    </div>
</div>
'''

    html_parts.append(f'''</head>
<body>
{ai_overlay}
<div class="page-wrapper">

    <!-- Sidebar navigation -->
    <nav class="sidebar">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 8px;">
            <h2 style="margin-bottom: 0; border-bottom: none; padding-bottom: 0;">Contents</h2>
            <button id="theme-toggle" style="background: none; border: none; cursor: pointer; color: var(--fg-muted); font-size: 16px; padding: 4px;" title="Toggle Dark/Light Mode">◑</button>
        </div>
        
        <input type="text" id="toc-search" placeholder="Search (Ctrl+K)..." style="width: 100%; padding: 6px 8px; margin-bottom: 12px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg); color: var(--fg); font-size: 13px;">
        
        <ul class="toc">
{sidebar_html}
        </ul>
    </nav>

    <!-- Main content -->
    <main class="content">
        <h1>{report_name}</h1>
            <p style="font-size: 12px; color: var(--fg-muted); margin-bottom: 4px;">Generated by <a href="https://github.com/djrien-ai/pbi-doc-generator" style="color: var(--fg-muted);"><strong>PBI Doc Generator</strong></a> v{version_str} &mdash; by <a href="https://www.linkedin.com/in/rienscheerlinck/" target="_blank" rel="noopener" style="color: var(--fg-muted);">Rien Scheerlinck</a></p>
{metadata_html}
{sections_html}
    </main>

</div>

<button class="back-to-top" id="backToTop" title="Back to top">↑</button>

''')

    # Add each feature in its own script block
    js_blocks = [
        JS_MERMAID_INIT,
        JS_BACK_TO_TOP,
        JS_SCROLL_SPY,
        JS_COLLAPSIBLE,
        JS_SEARCH,
        JS_COPY_BUTTONS,
        JS_THEME_TOGGLE,
        JS_AUTO_OPEN_DETAILS,
        JS_WIREFRAME_TOGGLES
    ]
    if enable_ai_enrichment:
        js_blocks.append(JS_AI_IMPORTER)
    
    for js_block in js_blocks:
        html_parts.append('<script>\n')
        html_parts.append(js_block.strip())
        html_parts.append('\n</script>\n')
        
    html_parts.append('</body>\n</html>')
    
    return "".join(html_parts)
