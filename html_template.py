"""
HTML template module for Power BI data documentation.

Generates a standalone HTML page with GitHub-style CSS, left sidebar
navigation, Mermaid.js relationship diagrams, alert boxes, and a
back-to-top button.
"""


from mermaid_js import MERMAID_JS

def generate_html(report_name: str, sections_html: str, sidebar_html: str) -> str:
    """Returns a complete standalone HTML document string.

    Args:
        report_name:   Display name of the Power BI report.
        sections_html: Pre-built HTML for every content section.
        sidebar_html:  Pre-built HTML for the sidebar ``<ul>`` tree.

    Returns:
        A full ``<!DOCTYPE html>`` string ready to be written to a file.
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report_name} — Data Documentation</title>
<script>
{MERMAID_JS}
</script>
<style>
/* ── CSS Variables ─────────────────────────────────────────────── */
:root {{
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
}}

/* ── Reset ─────────────────────────────────────────────────────── */
* {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}

/* ── Body ──────────────────────────────────────────────────────── */
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: var(--fg);
    background: var(--bg);
}}

/* ── Layout ────────────────────────────────────────────────────── */
.page-wrapper {{
    display: flex;
    min-height: 100vh;
}}

/* ── Sidebar ───────────────────────────────────────────────────── */
.sidebar {{
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
}}

.sidebar h2 {{
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--fg-muted);
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}}

.sidebar ul {{
    list-style: none;
}}

.sidebar > ul > li {{
    margin-bottom: 4px;
}}

.sidebar li a {{
    display: block;
    padding: 4px 8px;
    border-radius: 6px;
    color: var(--fg);
    text-decoration: none;
    transition: background 0.15s;
}}

.sidebar li a:hover {{
    background: var(--border-light);
    color: var(--accent);
}}

.sidebar li a.active {{
    background: var(--note-bg);
    color: var(--accent);
    font-weight: 600;
}}

.sidebar ul ul {{
    padding-left: 14px;
}}

.sidebar ul ul li a {{
    font-size: 12px;
    color: var(--fg-muted);
    padding: 2px 8px;
}}

.sidebar ul ul li a:hover {{
    color: var(--accent);
}}

/* ── Content ───────────────────────────────────────────────────── */
.content {{
    margin-left: var(--sidebar-width);
    max-width: 960px;
    padding: 40px 48px 80px;
}}

/* ── Back-to-top button ────────────────────────────────────────── */
.back-to-top {{
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
}}

.back-to-top.visible {{
    opacity: 1;
}}

.back-to-top:hover {{
    background: var(--accent-hover);
}}

/* ── Typography ────────────────────────────────────────────────── */
h1 {{
    font-size: 28px;
    font-weight: 700;
    margin: 0 0 8px;
    padding-bottom: 12px;
    border-bottom: 2px solid var(--border);
}}

h2 {{
    font-size: 22px;
    font-weight: 600;
    margin: 40px 0 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
    scroll-margin-top: 20px;
}}

h3 {{
    font-size: 17px;
    font-weight: 600;
    margin: 28px 0 12px;
    scroll-margin-top: 20px;
}}

h4 {{
    font-size: 15px;
    font-weight: 600;
    margin: 20px 0 8px;
    scroll-margin-top: 20px;
}}

p {{
    margin: 0 0 12px;
}}

a {{
    color: var(--accent);
    text-decoration: none;
}}

a:hover {{
    text-decoration: underline;
}}

hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 32px 0;
}}

/* ── Code ──────────────────────────────────────────────────────── */
code {{
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 13px;
    background: var(--code-bg);
    padding: 2px 6px;
    border-radius: 4px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}}

pre {{
    background: var(--code-bg);
    border: 1px solid var(--border-light);
    border-radius: 6px;
    padding: 16px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    overflow-x: hidden;
    margin: 0 0 16px;
}}

pre code {{
    background: none;
    padding: 0;
    font-size: 13px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}}

/* ── Tables ────────────────────────────────────────────────────── */
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 0 0 16px;
    font-size: 14px;
    table-layout: fixed;
}}

th, td {{
    border: 1px solid var(--border);
    padding: 8px 12px;
    text-align: left;
    vertical-align: top;
    white-space: normal;
    overflow-wrap: anywhere;
}}

th {{
    background: var(--code-bg);
    font-weight: 600;
}}

tr:nth-child(even) td {{
    background: var(--table-stripe);
}}

/* ── Alerts ────────────────────────────────────────────────────── */
.alert {{
    border-left: 4px solid;
    border-radius: 6px;
    padding: 14px 16px;
    margin: 16px 0;
    font-size: 14px;
}}

.alert .alert-title {{
    font-weight: 600;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
}}

.alert-note {{
    background: var(--note-bg);
    border-color: var(--note-border);
}}

.alert-note .alert-title {{
    color: var(--note-fg);
}}

.alert-tip {{
    background: var(--tip-bg);
    border-color: var(--tip-border);
}}

.alert-tip .alert-title {{
    color: var(--tip-fg);
}}

.alert-important {{
    background: var(--important-bg);
    border-color: var(--important-border);
}}

.alert-important .alert-title {{
    color: var(--important-fg);
}}

.alert-warning {{
    background: var(--warning-bg);
    border-color: var(--warning-border);
}}

.alert-warning .alert-title {{
    color: var(--warning-fg);
}}

.alert-caution {{
    background: var(--caution-bg);
    border-color: var(--caution-border);
}}

.alert-caution .alert-title {{
    color: var(--caution-fg);
}}

/* ── Lists ─────────────────────────────────────────────────────── */
ul, ol {{
    margin: 0 0 12px;
    padding-left: 24px;
}}

li {{
    margin-bottom: 4px;
}}

/* ── Mermaid ───────────────────────────────────────────────────── */
.mermaid {{
    margin: 16px 0;
    text-align: center;
}}

.mermaid svg {{
    max-width: 100%;
    height: auto;
}}

/* ── Misc ──────────────────────────────────────────────────────── */
.subtitle {{
    color: var(--fg-muted);
    font-size: 15px;
    margin-bottom: 24px;
}}

.section-anchor {{
    color: var(--fg-muted);
    text-decoration: none;
    font-weight: 400;
    margin-left: 6px;
    opacity: 0;
    transition: opacity 0.15s;
    font-size: 0.85em;
}}

h2:hover .section-anchor,
h3:hover .section-anchor {{
    opacity: 1;
}}

.section-anchor:hover {{
    color: var(--accent);
    text-decoration: none;
}}

strong {{
    font-weight: 600;
}}

/* ── Print ─────────────────────────────────────────────────────── */
@media print {{
    .sidebar, .back-to-top {{
        display: none !important;
    }}
    .content {{
        margin-left: 0;
        max-width: 100%;
        padding: 20px;
    }}
    table {{
        font-size: 11px;
    }}
    h2 {{
        page-break-before: always;
    }}
    h2:first-of-type {{
        page-break-before: avoid;
    }}
    pre {{
        white-space: pre-wrap;
        word-break: break-all;
    }}
}}

/* ── Responsive ────────────────────────────────────────────────── */
@media (max-width: 800px) {{
    .sidebar {{
        display: none;
    }}
    .content {{
        margin-left: 0;
        padding: 20px;
    }}
}}
</style>
</head>
<body>
<div class="page-wrapper">

    <!-- Sidebar navigation -->
    <nav class="sidebar">
        <h2>Contents</h2>
        {sidebar_html}
    </nav>

    <!-- Main content -->
    <main class="content">
        <h1>{report_name}</h1>
        <p style="font-size: 12px; color: var(--fg-muted); margin-bottom: 4px;">Generated by <a href="https://github.com/djrien-ai/pbi-doc-generator" style="color: var(--fg-muted);"><strong>PBI Doc Generator</strong></a> v0.4 &mdash; by Rien Scheerlinck</p>
        <p class="subtitle">Data layer reference for redevelopment. Complete data model and report page reference for redevelopment.</p>
        {sections_html}
    </main>

</div>

<!-- Back-to-top button -->
<button class="back-to-top" id="backToTop" title="Back to top" aria-label="Back to top">&#8593;</button>

<script>
    // ── Mermaid initialisation ────────────────────────────────────
    document.addEventListener("DOMContentLoaded", function () {{
        if (typeof mermaid !== "undefined") {{
            mermaid.initialize({{ startOnLoad: true, theme: "neutral" }});
        }}
    }});

    // ── Back-to-top visibility toggle ─────────────────────────────
    (function () {{
        var btn = document.getElementById("backToTop");
        window.addEventListener("scroll", function () {{
            if (window.scrollY > 300) {{
                btn.classList.add("visible");
            }} else {{
                btn.classList.remove("visible");
            }}
        }});
        btn.addEventListener("click", function () {{
            window.scrollTo({{ top: 0, behavior: "smooth" }});
        }});
    }})();

    // ── Scroll-based sidebar highlighting ─────────────────────────
    (function () {{
        var links = document.querySelectorAll(".sidebar a[href^='#']");
        if (!links.length) return;

        var sections = [];
        links.forEach(function (link) {{
            var id = link.getAttribute("href").slice(1);
            var el = document.getElementById(id);
            if (el) sections.push({{ el: el, link: link }});
        }});

        function highlight() {{
            var scrollY = window.scrollY + 40;
            var current = null;
            for (var i = 0; i < sections.length; i++) {{
                if (sections[i].el.offsetTop <= scrollY) {{
                    current = sections[i];
                }}
            }}
            links.forEach(function (l) {{ l.classList.remove("active"); }});
            if (current) current.link.classList.add("active");
        }}

        window.addEventListener("scroll", highlight);
        highlight();
    }})();
</script>
</body>
</html>"""
