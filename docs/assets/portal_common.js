
(function () {
    function safeGet(k) {
        try { return window.localStorage.getItem(k); } catch (e) { return null; }
    }
    function safeSet(k, v) {
        try { window.localStorage.setItem(k, v); } catch (e) { /* sandboxed */ }
    }
    window.PbiStorage = { get: safeGet, set: safeSet };

    window.PbiNavigate = function (href) {
        if (!href) return;
        if (window.PBIDOC_SHELL && typeof window.PBIDOC_SHELL.nav === "function" && !/^(#|[a-z][a-z0-9+.-]*:)/i.test(href)) {
            var k = href.indexOf("#");
            window.PBIDOC_SHELL.nav(k < 0 ? href : href.slice(0, k), k < 0 ? "" : href.slice(k + 1));
            return;
        }
        window.location.href = href;
    };

    var saved = safeGet("pbidoc-v1-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);

    function triggerDownload(filename, mime, content) {
        var blob = new Blob([content], { type: mime });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 250);
    }

    function slugFile(s) {
        return String(s || "export").replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "export";
    }

    function buildMeasureMarkdown(rootId) {
        var g = window.PBI_E2E_GRAPH;
        if (!g || !g.nodes || !g.nodes[rootId]) return null;
        var nodes = g.nodes;
        var adj = {};
        (g.edges || []).forEach(function (e) {
            if (!adj[e.from]) adj[e.from] = [];
            adj[e.from].push(e);
        });
        var visited = {};
        var order = [];
        var queue = [rootId];
        visited[rootId] = 0;
        while (queue.length) {
            var cur = queue.shift();
            order.push(cur);
            (adj[cur] || []).forEach(function (e) {
                if (visited[e.to] === undefined) {
                    visited[e.to] = visited[cur] + 1;
                    queue.push(e.to);
                }
            });
        }
        var root = nodes[rootId];
        var byKind = { source: [], dataflow_query: [], expression: [], table: [], calc_table: [], calc_column: [], measure: [] };
        order.forEach(function (id) {
            var n = nodes[id];
            if (n && byKind[n.kind]) byKind[n.kind].push(n);
        });

        var lines = [
            "# Measure End-to-End Lineage Specification: [" + root.name + "]",
            "",
            "- **Semantic Model:** " + (root.model || "-") + " (Workspace: " + (root.workspace || "-") + ")",
            "- **Host Table:** `" + (root.table || "-") + "`" + (root.folder ? " | **Folder:** `" + root.folder + "`" : "") + (root.format ? " | **Format:** `" + root.format + "`" : ""),
            root.report ? ("- **Report Scope:** Thin-Report Measure in `" + root.report + "`") : "- **Scope:** Shared Semantic Model Measure",
            ""
        ];
        if (root.description) {
            lines.push("> " + root.description, "");
        }
        lines.push("## 1. Primary DAX Formula", "", "```dax", (root.code || ""), "```", "");

        lines.push("## 2. Physical Data Sources & Native SQL (" + byKind.source.length + ")", "");
        if (!byKind.source.length) {
            lines.push("_No external physical source dependencies detected._", "");
        } else {
            byKind.source.forEach(function (s, idx) {
                lines.push("### 2." + (idx + 1) + " " + s.name + " (" + (s.source_type || "Source") + ")");
                if (s.server) lines.push("- **Server / Endpoint:** `" + s.server + "`");
                if (s.database) lines.push("- **Database:** `" + s.database + "`");
                if (s.code) {
                    lines.push("", "```sql", s.code, "```");
                }
                lines.push("");
            });
        }

        lines.push("## 3. Upstream Dataflow Transformations (Gen1 & Gen2) (" + byKind.dataflow_query.length + ")", "");
        if (!byKind.dataflow_query.length) {
            lines.push("_This measure does not traverse any upstream Dataflow._", "");
        } else {
            byKind.dataflow_query.forEach(function (q, idx) {
                lines.push("### 3." + (idx + 1) + " " + (q.group || "Dataflow") + " -> `" + q.name + "` (" + (q.generation || "Gen1") + ")");
                lines.push("- **Workspace:** " + (q.workspace || "-"));
                if (q.destination && q.destination.table) {
                    lines.push("- **OneLake Destination:** " + (q.destination.kind || "Lakehouse") + " `" + q.destination.table + "`");
                }
                if (q.step_items && q.step_items.length) {
                    lines.push("- **Transformation Steps:**");
                    q.step_items.forEach(function (st, si) {
                        lines.push("  " + (si + 1) + ". **" + st.name + "** (`" + (st.op || "M") + "`): " + (st.summary || ""));
                    });
                }
                if (q.code) lines.push("", "```powerquery", q.code, "```");
                lines.push("");
            });
        }

        var pqNodes = byKind.expression.concat(byKind.table).concat(byKind.calc_table);
        lines.push("## 4. Semantic Model Tables & Power Query (" + pqNodes.length + ")", "");
        pqNodes.forEach(function (t, idx) {
            lines.push("### 4." + (idx + 1) + " `" + t.name + "` (" + (t.storage_mode || t.kind) + ")");
            if (t.step_items && t.step_items.length) {
                t.step_items.forEach(function (st, si) {
                    lines.push("- Step " + (si + 1) + " **" + st.name + "**: " + (st.summary || st.op || ""));
                });
            }
            if (t.code) lines.push("", "```" + (t.lang || "powerquery"), t.code, "```");
            lines.push("");
        });

        if (byKind.measure.length > 1) {
            lines.push("## 5. Referenced DAX Measure Chain (" + byKind.measure.length + ")", "");
            byKind.measure.slice().reverse().forEach(function (m, idx) {
                lines.push("### 5." + (idx + 1) + " `[" + m.name + "]` (Table: `" + (m.table || "-") + "`)");
                lines.push("", "```dax", (m.code || ""), "```", "");
            });
        }
        return { name: root.name, markdown: lines.join("\n") };
    }

    function exportMeasureSpec(rootId, asWordDoc) {
        var res = buildMeasureMarkdown(rootId);
        if (!res) return;
        var base = "Measure_Lineage_" + slugFile(res.name);
        if (!asWordDoc) {
            triggerDownload(base + ".md", "text/markdown;charset=utf-8", res.markdown);
            return;
        }
        var esc = function (s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); };
        var htmlBody = res.markdown
            .replace(/```([a-z]*)\n([\s\S]*?)```/g, function (_, lang, code) {
                return '<pre style="background:#f1f5f9;border:1px solid #cbd5e1;padding:10px;font-family:Consolas,monospace;font-size:10pt;white-space:pre-wrap">' + esc(code) + '</pre>';
            })
            .replace(/^### (.+)$/gm, "<h3>$1</h3>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/^# (.+)$/gm, "<h1>$1</h1>")
            .replace(/^- (.+)$/gm, "<p style='margin:2px 0'>&bull; $1</p>")
            .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
            .replace(/`([^`]+)`/g, "<code>$1</code>");
        var wordHtml = '<!DOCTYPE html><html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>' +
            esc(res.name) + '</title><style>body{font-family:Segoe UI,Calibri,sans-serif;font-size:11pt;color:#0f172a}h1{color:#072854}h2{color:#0b63ce;border-bottom:1px solid #cbd5e1;padding-bottom:4px;margin-top:18px}code{font-family:Consolas,monospace;background:#eef2f7;padding:1px 4px}</style></head><body>' +
            htmlBody + '</body></html>';
        triggerDownload(base + ".doc", "application/msword;charset=utf-8", wordHtml);
    }

    function csvEscape(v) {
        var s = String(v == null ? "" : v).replace(/\r?\n/g, " ").trim();
        if (/[",\n;]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
        return s;
    }

    function getPageModelMeta() {
        var slugEl = document.querySelector('meta[name="pbi-model-slug"]');
        var nameEl = document.querySelector('meta[name="pbi-model-name"]');
        var idEl = document.querySelector('meta[name="pbi-model-id"]');
        var wsEl = document.querySelector('meta[name="pbi-model-ws"]');
        return {
            isModelPage: !!(slugEl && slugEl.content),
            slug: slugEl ? slugEl.content : "",
            name: nameEl ? nameEl.content : "",
            id: idEl ? idEl.content : "",
            workspace: wsEl ? wsEl.content : ""
        };
    }

    function isStudioServer() {
        return (location.protocol === "http:" || location.protocol === "https:") &&
            (location.hostname === "127.0.0.1" || location.hostname === "localhost");
    }

    function buildModelSpecFromGraph(modelId, modelName, modelWs) {
        var g = window.PBI_E2E_GRAPH || {};
        var nodes = g.nodes || {};
        var tables = [];
        var measures = [];
        var sources = [];
        var dataflows = [];
        Object.keys(nodes).forEach(function (k) {
            var n = nodes[k];
            if (!n) return;
            if (modelId && n.model_id && n.model_id !== modelId) return;
            if (!modelId && modelName && n.model && n.model !== modelName) return;
            if (n.kind === "table" || n.kind === "calc_table") tables.push(n);
            else if (n.kind === "measure" && !n.report) measures.push(n);
        });
        // Collect upstream sources/dataflows linked to this model's nodes
        var modelNodeSet = new Set();
        tables.forEach(function (t) { modelNodeSet.add(t.id); });
        measures.forEach(function (m) { modelNodeSet.add(m.id); });
        var adj = {};
        (g.edges || []).forEach(function (e) {
            if (!adj[e.from]) adj[e.from] = [];
            adj[e.from].push(e.to);
        });
        var q = Array.from(modelNodeSet);
        var vis = new Set(q);
        while (q.length) {
            var cur = q.shift();
            (adj[cur] || []).forEach(function (nx) {
                if (!vis.has(nx)) { vis.add(nx); q.push(nx); }
            });
        }
        vis.forEach(function (id) {
            var n = nodes[id];
            if (!n) return;
            if (n.kind === "source") sources.push(n);
            else if (n.kind === "dataflow_query") dataflows.push(n);
        });

        tables.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || "")); });
        measures.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || "")); });

        var md = [
            "# Semantic Model Technical Blueprint: " + (modelName || "Model"),
            "",
            "- **Workspace:** " + (modelWs || "-"),
            "- **Tables:** " + tables.length + " | **DAX Measures:** " + measures.length + " | **Upstream Sources:** " + sources.length,
            ""
        ];
        if (sources.length) {
            md.push("## 1. Data Sources & Native SQL (" + sources.length + ")", "");
            sources.forEach(function (s) {
                md.push("- **" + (s.name || "Source") + "** (" + (s.source_type || "Connector") + ")" + (s.database ? " - DB: `" + s.database + "`" : ""));
                if (s.code) md.push("", "```sql", s.code, "```", "");
            });
            md.push("");
        }
        if (dataflows.length) {
            md.push("## 2. Upstream Dataflow Entities (" + dataflows.length + ")", "");
            dataflows.forEach(function (d) {
                md.push("- **" + (d.group || "Dataflow") + "** -> `" + (d.name || "") + "` (" + (d.generation || "Gen1") + ", Workspace: " + (d.workspace || "-") + ")");
            });
            md.push("");
        }
        md.push("## 3. Model Tables & Columns (" + tables.length + ")", "");
        tables.forEach(function (t) {
            md.push("### Table: `" + t.name + "` (" + (t.storage_mode || t.kind || "Table") + ")");
            var cols = t.columns || [];
            if (cols.length) {
                cols.forEach(function (c) {
                    var cname = typeof c === "string" ? c : (c.name || "");
                    var ctype = (typeof c === "object" && c.type) ? " (`" + c.type + "`)" : "";
                    md.push("- `" + cname + "`" + ctype);
                });
            }
            if (t.code) md.push("", "```" + (t.lang || "powerquery"), t.code, "```");
            md.push("");
        });
        md.push("## 4. DAX Measure Catalog (" + measures.length + ")", "");
        measures.forEach(function (m) {
            md.push("### `[" + m.name + "]` (Table: `" + (m.table || "-") + "`" + (m.folder ? ", Folder: `" + m.folder + "`" : "") + ")");
            if (m.description) md.push("> " + m.description);
            md.push("", "```dax", (m.code || ""), "```", "");
        });

        var csvRows = ["ObjectType,Table,Name,DataTypeOrFolder,Format,StorageOrSource,Expression"];
        tables.forEach(function (t) {
            (t.columns || []).forEach(function (c) {
                var cname = typeof c === "string" ? c : (c.name || "");
                var ctype = typeof c === "object" ? (c.type || "") : "";
                var cfmt = typeof c === "object" ? (c.format || "") : "";
                var csrc = typeof c === "object" ? (c.source || "") : (t.storage_mode || "");
                var cexpr = typeof c === "object" ? (c.expr || "") : "";
                csvRows.push(["Column", t.name, cname, ctype, cfmt, csrc, cexpr].map(csvEscape).join(","));
            });
        });
        measures.forEach(function (m) {
            csvRows.push(["Measure", m.table || "", m.name || "", m.folder || "General", m.format || "", "DAX", m.code || ""].map(csvEscape).join(","));
        });
        // Also harvest DOM columns if graph columns are compact strings
        if (tables.length === 0 && document.querySelectorAll("details.table-blueprint").length) {
            document.querySelectorAll("details.table-blueprint").forEach(function (det) {
                var tTitle = (det.querySelector("summary span") && det.querySelector("summary span").textContent || "Table").split(":")[0].trim();
                det.querySelectorAll("tbody tr").forEach(function (tr) {
                    var tds = tr.querySelectorAll("td");
                    if (tds.length >= 4) {
                        csvRows.push(["Column", tTitle, tds[0].textContent, tds[1].textContent, tds[3].textContent, tds[2].textContent, tds[4] ? tds[4].textContent : ""].map(csvEscape).join(","));
                    }
                });
            });
        }

        return {
            markdown: md.join("\n"),
            csv: "\uFEFF" + csvRows.join("\r\n")
        };
    }

    function exportModelHandover(modelSlug, fmt) {
        var meta = getPageModelMeta();
        var g = window.PBI_E2E_GRAPH || {};
        var models = g.models || [];
        var mEntry = models.find(function (m) { return m.slug === modelSlug || m.id === meta.id || m.name === meta.name; }) || {};
        var mId = (meta.isModelPage && meta.slug === modelSlug && meta.id) ? meta.id : (mEntry.id || "");
        var mName = mEntry.name || meta.name || modelSlug || "Model";
        var mWs = mEntry.workspace || meta.workspace || "";
        var built = buildModelSpecFromGraph(mId, mName, mWs);
        var base = slugFile(mName);
        if (fmt === "csv") {
            triggerDownload(base + "_Data_Dictionary.csv", "text/csv;charset=utf-8", built.csv);
            return;
        }
        if (fmt === "md") {
            triggerDownload(base + "_Blueprint.md", "text/markdown;charset=utf-8", built.markdown);
            return;
        }
        var esc = function (s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); };
        var htmlBody = built.markdown
            .replace(/```([a-z]*)\n([\s\S]*?)```/g, function (_, _l, code) {
                return '<pre style="background:#f1f5f9;border:1px solid #cbd5e1;padding:10px;font-family:Consolas,monospace;font-size:9.5pt;white-space:pre-wrap">' + esc(code) + '</pre>';
            })
            .replace(/^### (.+)$/gm, "<h3>$1</h3>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/^# (.+)$/gm, "<h1>$1</h1>")
            .replace(/^- (.+)$/gm, "<p style='margin:2px 0'>&bull; $1</p>")
            .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
            .replace(/`([^`]+)`/g, "<code>$1</code>");
        var wordHtml = '<!DOCTYPE html><html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>' +
            esc(mName) + '</title><style>body{font-family:Segoe UI,Calibri,sans-serif;font-size:10.5pt;color:#0f172a}h1{color:#072854}h2{color:#0b63ce;border-bottom:1px solid #cbd5e1;padding-bottom:4px;margin-top:18px}code{font-family:Consolas,monospace;background:#eef2f7;padding:1px 4px}</style></head><body>' +
            htmlBody + '</body></html>';
        triggerDownload(base + "_Handover_Spec.doc", "application/msword;charset=utf-8", wordHtml);
    }

    function exportGovernanceCsv() {
        var rows = ["SemanticModel,Workspace,Severity,Finding,RecommendedAction"];
        document.querySelectorAll("#tab-health tbody tr[data-health-sev]").forEach(function (tr) {
            var tds = tr.querySelectorAll("td");
            if (tds.length >= 5) {
                rows.push([tds[0].textContent, tds[1].textContent, tds[2].textContent, tds[3].textContent, tds[4].textContent].map(csvEscape).join(","));
            }
        });
        if (rows.length === 1) {
            rows.push('"All Models","-","OK","Healthy","Zero governance warnings detected"');
        }
        triggerDownload("PBI_Governance_Remediation_Backlog.csv", "text/csv;charset=utf-8", "\uFEFF" + rows.join("\r\n"));
    }

    var _ctrlPOpened = [];
    window.addEventListener("beforeprint", function () {
        document.querySelectorAll("details.dax-folder-details, details.dax-table-group, details.principals-details, #tab-workspaces.active details.section-accordion").forEach(function (d) {
            if (!d.open) { d.open = true; _ctrlPOpened.push(d); }
        });
    });
    window.addEventListener("afterprint", function () {
        while (_ctrlPOpened.length) {
            var d = _ctrlPOpened.pop();
            try { d.open = false; } catch (e) {}
        }
    });

    function runCleanPrint(preset) {
        var prevTheme = document.documentElement.getAttribute("data-theme");
        document.documentElement.setAttribute("data-theme", "light");
        var openedDetails = [];
        var alwaysOpenSel = "details.dax-folder-details, details.dax-table-group, details.principals-details, #tab-workspaces.active details.section-accordion";
        var fullOpenSel = "details.table-blueprint, details.dax-folder-details, details.dax-table-group, details.section-accordion, details.principals-details";
        document.querySelectorAll(preset === "full" ? fullOpenSel : alwaysOpenSel).forEach(function (d) {
            if (!d.open) { d.open = true; openedDetails.push(d); }
        });
        var modal = document.getElementById("pbiPublishModal");
        if (modal) modal.classList.remove("is-open");

        var restored = false;
        function restoreAfterPrint() {
            if (restored) return;
            restored = true;
            if (prevTheme) document.documentElement.setAttribute("data-theme", prevTheme);
            else document.documentElement.removeAttribute("data-theme");
            openedDetails.forEach(function (d) { d.open = false; });
            document.querySelectorAll(".section[data-print-hide]").forEach(function (s) { s.removeAttribute("data-print-hide"); });
            window.removeEventListener("afterprint", restoreAfterPrint);
        }
        window.addEventListener("afterprint", restoreAfterPrint);
        setTimeout(function () {
            if (window.PBIDOC_SHELL && typeof window.PBIDOC_SHELL.print === "function") {
                window.PBIDOC_SHELL.print();
            } else {
                window.print();
            }
            setTimeout(restoreAfterPrint, 1200);
        }, 80);
    }

    function openPublishModal(initialMode) {
        var meta = getPageModelMeta();
        var g = window.PBI_E2E_GRAPH || {};
        var models = g.models || [];
        var studio = isStudioServer();

        var modal = document.getElementById("pbiPublishModal");
        if (!modal) {
            modal = document.createElement("div");
            modal.id = "pbiPublishModal";
            modal.className = "pbi-modal-backdrop";
            document.body.appendChild(modal);
        }

        var scope = (initialMode === "model" || meta.isModelPage) ? "model" : "catalog";
        if (scope === "model" && !meta.slug && models.length) {
            meta.slug = models[0].slug || "";
            meta.name = models[0].name || "";
        }
        var savedSpUrl = safeGet("pbidoc-v11-sp-url") || "";

        function renderModalBody() {
            var curSlug = meta.slug || (models[0] && models[0].slug) || "";
            var curModelObj = models.find(function (m) { return m.slug === curSlug; }) || { name: meta.name || curSlug, workspace: meta.workspace || "" };
            var curModelLabel = curModelObj.name || meta.name || "Selected Model";
            var modelPickerHtml = "";
            if (scope === "model" && models.length > 1) {
                modelPickerHtml = '<select id="pubModelSelect" class="sort-select" style="max-width:210px;padding:4px 8px;font-size:11.5px" aria-label="Choose semantic model">' +
                    models.map(function (m) {
                        var sl = m.slug || "";
                        var sel = (sl === curSlug) ? " selected" : "";
                        return '<option value="' + sl.replace(/"/g, "&quot;") + '"' + sel + '>' + (m.workspace ? m.workspace + " - " : "") + m.name + '</option>';
                    }).join("") + '</select>';
            }

            var chaptersHtml = "";
            if (scope === "model" && meta.isModelPage && curSlug === getPageModelMeta().slug) {
                chaptersHtml =
                    '<div class="print-chap-pills">' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-overview" checked> 1. Overview</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-schema" checked> 2. Star Schema</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-tables" checked> 3. Tables &amp; SQL</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-dax" checked> 4. DAX Catalog</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-lineage"> 5. Lineage</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-security" checked> 6. RLS &amp; Reports</label>' +
                    '</div>';
            }

            var validInitialSp = /^https:\/\//i.test((savedSpUrl || "").trim());
            var spCardBody = studio
                ? ('<input type="url" id="pubSpUrlInput" value="' + savedSpUrl.replace(/"/g, "&quot;") + '" placeholder="https://contoso.sharepoint.com/sites/BI/Shared%20Documents/Portal" style="width:100%;padding:7px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--fg);font-size:12px">' +
                   '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">' +
                     '<label style="font-size:11.5px;color:var(--fg-muted);display:inline-flex;align-items:center;gap:5px"><input type="checkbox" id="pubSpAspxChk"> Use <code>.aspx</code> extension (strict SharePoint tenants)</label>' +
                   '</div>' +
                   '<div id="pubSpStatus" style="display:none;font-size:12px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--surface)"></div>' +
                   '<div class="publish-card-actions">' +
                     '<button type="button" class="publish-top-btn" id="btnDirectPublishSp"' + (validInitialSp ? '' : ' disabled title="Paste a https:// SharePoint Document Library URL above first"') + '>Publish Directly to SharePoint &rarr;</button>' +
                     '<button type="button" class="lin-btn" id="btnDownloadSpFile">Download SharePoint File</button>' +
                   '</div>')
                : ('<p>Downloads a SharePoint-hardened single file (sandboxed storage safe, zero external assets). Upload to any SharePoint Document Library, or run <code>pbi-catalog studio</code> for 1-click direct URL publishing.</p>' +
                   '<div class="publish-card-actions">' +
                     '<button type="button" class="publish-top-btn" id="btnDownloadSpFile">Download SharePoint File (.html)</button>' +
                   '</div>');

            modal.innerHTML =
                '<div class="pbi-modal" role="dialog" aria-modal="true" aria-labelledby="pubModalTitle">' +
                  '<div class="pbi-modal-hdr">' +
                    '<div>' +
                      '<h3 id="pubModalTitle">Export &amp; Publish Documentation</h3>' +
                      '<div style="font-size:12px;color:var(--fg-muted);margin-top:2px">' +
                        (scope === "model"
                          ? ('Scope: <b>Single Semantic Model</b> (' + curModelLabel.replace(/</g, "&lt;") + ') - isolated without other models')
                          : ('Scope: <b>Entire Documentation Catalog</b> (' + (models.length || 1) + ' model' + (models.length === 1 ? '' : 's') + ')')) +
                      '</div>' +
                    '</div>' +
                    '<button type="button" class="xray-close-btn" data-close-publish="1" aria-label="Close modal">&times; Close</button>' +
                  '</div>' +
                  '<div class="pbi-modal-body">' +
                    '<div class="publish-scope-bar">' +
                      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
                        '<div class="view-toggle" role="group" aria-label="Export scope">' +
                          (models.length > 0 || meta.isModelPage
                            ? '<button type="button" class="view-btn ' + (scope === "model" ? "active" : "") + '" data-pub-scope="model">This Semantic Model</button>'
                            : '') +
                          '<button type="button" class="view-btn ' + (scope === "catalog" ? "active" : "") + '" data-pub-scope="catalog">Entire Catalog (' + (models.length || 1) + ')</button>' +
                        '</div>' +
                        modelPickerHtml +
                      '</div>' +
                      '<label style="font-size:12px;display:inline-flex;align-items:center;gap:6px;cursor:pointer">' +
                        '<input type="checkbox" id="pubAnonChk"> Anonymize owners &amp; emails' +
                      '</label>' +
                    '</div>' +

                    '<div class="publish-grid">' +
                      '<div class="publish-card">' +
                        '<h4>1. Print or Save as Clean PDF</h4>' +
                        '<p>' + (scope === "model"
                          ? "A4 print-optimized layout (hides navigation chrome, switches to crisp light ink, prevents split code/tables)."
                          : "Prints the active catalog view cleanly as an executive PDF inventory.") + '</p>' +
                        chaptersHtml +
                        '<div class="publish-card-actions">' +
                          (scope === "model"
                            ? ('<button type="button" class="publish-top-btn" data-pub-print="exec">Print Executive Summary PDF</button>' +
                               '<button type="button" class="lin-btn" data-pub-print="full">Print Full Technical Blueprint</button>')
                            : '<button type="button" class="publish-top-btn" data-pub-print="catalog">Print Current Catalog View</button>') +
                        '</div>' +
                      '</div>' +

                      '<div class="publish-card">' +
                        '<h4>2. Standalone HTML or Offline .zip</h4>' +
                        '<p>' + (scope === "model"
                          ? "Self-contained interactive HTML file for <b>" + curModelLabel.replace(/</g, "&lt;") + "</b> (Star Schema, formatted DAX, SQL &amp; Report X-Ray wireframes in 1 file)."
                          : "Share the complete multi-model portal by email, network drive, or static web server.") + '</p>' +
                        '<div class="publish-card-actions">' +
                          (scope === "model"
                            ? '<button type="button" class="publish-top-btn" data-pub-html="model-single">Download Standalone Model (.html)</button>'
                            : ('<button type="button" class="publish-top-btn" data-pub-html="catalog-single">Single-File Portal (.html)</button>' +
                               (studio ? '<button type="button" class="lin-btn" data-pub-html="catalog-zip">Offline Site Bundle (.zip)</button>' : ''))) +
                        '</div>' +
                      '</div>' +

                      '<div class="publish-card">' +
                        '<h4>3. SharePoint Online</h4>' +
                        '<p>Publish ' + (scope === "model" ? ('<b>' + curModelLabel.replace(/</g, "&lt;") + '</b>') : 'the <b>Entire Catalog</b>') + ' to a SharePoint Document Library using your Windows / Edge session.</p>' +
                        spCardBody +
                      '</div>' +

                      '<div class="publish-card">' +
                        '<h4>' + (scope === "model" ? "4. Editable Spec &amp; Data Dictionary" : "4. Portfolio Inventory &amp; Governance Backlog") + '</h4>' +
                        '<p>' + (scope === "model"
                          ? "Generate handover files for Confluence, Word, Git, or Excel governance reviews."
                          : "Export portfolio inventory &amp; prioritized governance findings.") + '</p>' +
                        '<div class="publish-card-actions">' +
                          (scope === "model"
                            ? ('<button type="button" class="lin-btn" data-pub-spec="doc">Word Spec (.doc)</button>' +
                               '<button type="button" class="lin-btn" data-pub-spec="md">Markdown (.md)</button>' +
                               '<button type="button" class="lin-btn" data-pub-spec="csv">Data Dictionary (.csv)</button>')
                            : ('<button type="button" class="lin-btn" data-export-catalog-md="1">Catalog Inventory (.md)</button>' +
                               '<button type="button" class="lin-btn" data-pub-gov-csv="1">Governance Backlog (.csv)</button>')) +
                        '</div>' +
                      '</div>' +
                    '</div>' +
                  '</div>' +
                '</div>';

            var selEl = modal.querySelector("#pubModelSelect");
            if (selEl) {
                selEl.addEventListener("change", function () {
                    meta.slug = selEl.value;
                    var mFound = models.find(function (m) { return m.slug === meta.slug; });
                    if (mFound) meta.name = mFound.name;
                    renderModalBody();
                });
            }
            var spInpEl = modal.querySelector("#pubSpUrlInput");
            var spBtnEl = modal.querySelector("#btnDirectPublishSp");
            if (spInpEl && spBtnEl) {
                spInpEl.addEventListener("input", function () {
                    var okUrl = /^https:\/\//i.test((spInpEl.value || "").trim());
                    spBtnEl.disabled = !okUrl;
                    spBtnEl.title = okUrl ? "" : "Paste a https:// SharePoint Document Library URL above first";
                });
            }
        }

        renderModalBody();
        modal.classList.add("is-open");

        modal.onclick = function (ev) {
            if (ev.target === modal || ev.target.closest("[data-close-publish]")) {
                modal.classList.remove("is-open");
                return;
            }
            var scBtn = ev.target.closest("[data-pub-scope]");
            if (scBtn) {
                scope = scBtn.getAttribute("data-pub-scope");
                if (scope === "model" && !meta.slug && models.length) {
                    meta.slug = models[0].slug || "";
                    meta.name = models[0].name || "";
                }
                renderModalBody();
                return;
            }
            var anonFlag = (modal.querySelector("#pubAnonChk") && modal.querySelector("#pubAnonChk").checked) ? "1" : "0";
            var curSlug = (modal.querySelector("#pubModelSelect") && modal.querySelector("#pubModelSelect").value) || meta.slug || "";

            var prBtn = ev.target.closest("[data-pub-print]");
            if (prBtn) {
                var pMode = prBtn.getAttribute("data-pub-print");
                if (pMode === "catalog") {
                    runCleanPrint("exec");
                    return;
                }
                var pageMeta = getPageModelMeta();
                if (!pageMeta.isModelPage || (curSlug && pageMeta.slug !== curSlug)) {
                    var targetHref = (pageMeta.isModelPage ? (curSlug + ".html") : ("models/" + curSlug + ".html")) + "?autoprint=" + pMode;
                    modal.classList.remove("is-open");
                    window.PbiNavigate(targetHref);
                    return;
                }
                var chChecks = modal.querySelectorAll(".pub-ch-chk");
                if (chChecks.length) {
                    chChecks.forEach(function (chk) {
                        var sec = document.getElementById(chk.value);
                        if (!sec) return;
                        if (!chk.checked) sec.setAttribute("data-print-hide", "1");
                        else sec.removeAttribute("data-print-hide");
                    });
                }
                runCleanPrint(pMode);
                return;
            }

            var htmlBtn = ev.target.closest("[data-pub-html]");
            if (htmlBtn) {
                var hKind = htmlBtn.getAttribute("data-pub-html");
                if (studio) {
                    if (hKind === "model-single") {
                        window.location.href = "/api/export-site?format=single&model=" + encodeURIComponent(curSlug) + "&anonymous=" + anonFlag;
                    } else if (hKind === "catalog-zip") {
                        window.location.href = "/api/export-site?format=zip&anonymous=" + anonFlag;
                    } else {
                        window.location.href = "/api/export-site?format=single&anonymous=" + anonFlag;
                    }
                } else {
                    var clone = document.documentElement.cloneNode(true);
                    var mRem = clone.querySelector("#pbiPublishModal");
                    if (mRem) mRem.remove();
                    if (hKind === "model-single") clone.setAttribute("data-standalone-model", "1");
                    triggerDownload(slugFile(hKind === "model-single" ? (curSlug + "_Documentation") : "PBI_Portal") + ".html", "text/html;charset=utf-8", "<!DOCTYPE html>\n" + clone.outerHTML);
                }
                return;
            }

            var dlSpBtn = ev.target.closest("#btnDownloadSpFile");
            if (dlSpBtn) {
                var useAspx = (modal.querySelector("#pubSpAspxChk") && modal.querySelector("#pubSpAspxChk").checked) ? "1" : "0";
                if (studio) {
                    var qModel = (scope === "model" && curSlug) ? ("&model=" + encodeURIComponent(curSlug)) : "";
                    window.location.href = "/api/export-site?format=single&aspx=" + useAspx + "&anonymous=" + anonFlag + qModel;
                } else {
                    var cloneSp = document.documentElement.cloneNode(true);
                    var mRem2 = cloneSp.querySelector("#pbiPublishModal");
                    if (mRem2) mRem2.remove();
                    if (scope === "model") cloneSp.setAttribute("data-standalone-model", "1");
                    var ext = useAspx === "1" ? ".aspx" : ".html";
                    triggerDownload(slugFile(scope === "model" ? (curSlug + "_SharePoint") : "PBI_Portal_SharePoint") + ext, "text/html;charset=utf-8", "<!DOCTYPE html>\n" + cloneSp.outerHTML);
                }
                return;
            }

            var pubSpBtn = ev.target.closest("#btnDirectPublishSp");
            if (pubSpBtn) {
                var urlInp = modal.querySelector("#pubSpUrlInput");
                var statusBox = modal.querySelector("#pubSpStatus");
                var spTarget = (urlInp && urlInp.value || "").trim();
                if (!spTarget) {
                    if (statusBox) {
                        statusBox.style.display = "block";
                        statusBox.style.color = "var(--bad)";
                        statusBox.innerHTML = "Paste a SharePoint Document Library folder URL first (e.g. <code>https://tenant.sharepoint.com/sites/BI/Shared%20Documents</code>).";
                    }
                    return;
                }
                safeSet("pbidoc-v11-sp-url", spTarget);
                savedSpUrl = spTarget;
                var aspxBool = !!(modal.querySelector("#pubSpAspxChk") && modal.querySelector("#pubSpAspxChk").checked);
                pubSpBtn.disabled = true;
                if (statusBox) {
                    statusBox.style.display = "block";
                    statusBox.style.color = "var(--fg)";
                    statusBox.innerHTML = "Authenticating via Windows / Edge SSO &amp; uploading to SharePoint Online...";
                }
                fetch("/api/publish-sharepoint", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        target_url: spTarget,
                        scope: scope,
                        model_slug: (scope === "model" ? curSlug : ""),
                        anonymous: anonFlag === "1",
                        aspx: aspxBool
                    })
                }).then(function (r) { return r.json(); }).then(function (res) {
                    pubSpBtn.disabled = false;
                    if (!statusBox) return;
                    if (res.ok) {
                        statusBox.style.color = "var(--ok)";
                        statusBox.innerHTML = "<b>Published to SharePoint!</b> (" + (res.size_kb || 0) + " KB) &bull; <a href='" + String(res.web_url || spTarget).replace(/'/g, "%27") + "' target='_blank' rel='noopener' style='font-weight:700;color:var(--accent)'>Open on SharePoint &rarr;</a>";
                    } else {
                        statusBox.style.color = "var(--bad)";
                        statusBox.innerHTML = "<b>SharePoint upload failed:</b> " + String(res.error || "Unknown error").replace(/</g, "&lt;");
                    }
                }).catch(function (err) {
                    pubSpBtn.disabled = false;
                    if (statusBox) {
                        statusBox.style.color = "var(--bad)";
                        statusBox.textContent = "Network error: " + err;
                    }
                });
                return;
            }

            var specBtn = ev.target.closest("[data-pub-spec]");
            if (specBtn) {
                exportModelHandover(curSlug, specBtn.getAttribute("data-pub-spec"));
                return;
            }

            var govCsvBtn = ev.target.closest("[data-pub-gov-csv]");
            if (govCsvBtn) {
                exportGovernanceCsv();
                return;
            }
        };
    }

    // Reveal Studio-only links only when served by local Studio HTTP server, and support ?autoprint=exec|full
    document.addEventListener("DOMContentLoaded", function () {
        if (isStudioServer()) {
            document.querySelectorAll(".studio-only-link").forEach(function (el) {
                el.style.display = "";
            });
        }
        try {
            var params = new URLSearchParams(location.search || "");
            var ap = params.get("autoprint");
            if (ap === "exec" || ap === "full") {
                if (window.history && typeof window.history.replaceState === "function") {
                    params.delete("autoprint");
                    var cleanQs = params.toString();
                    window.history.replaceState({}, document.title, location.pathname + (cleanQs ? ("?" + cleanQs) : "") + location.hash);
                }
                setTimeout(function () { runCleanPrint(ap); }, 260);
            }
        } catch (e) {}
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            var m = document.getElementById("pbiPublishModal");
            if (m && m.classList.contains("is-open")) m.classList.remove("is-open");
        }
    });

    document.addEventListener("change", function (e) {
        var sw = e.target.closest("select.model-switcher-select");
        if (sw && sw.value) {
            window.PbiNavigate(sw.value);
        }
    });

    document.addEventListener("click", function (e) {
        var openPub = e.target.closest("[data-open-publish-modal]");
        if (openPub) {
            e.preventDefault();
            openPublishModal(openPub.getAttribute("data-open-publish-modal") || "");
            return;
        }
        var dlGov = e.target.closest("[data-export-gov-csv]");
        if (dlGov) {
            e.preventDefault();
            exportGovernanceCsv();
            return;
        }
        var expMenuBtn = e.target.closest("[data-toggle-export-menu]");
        if (expMenuBtn) {
            e.stopPropagation();
            var menu = expMenuBtn.parentElement && expMenuBtn.parentElement.querySelector(".export-dropdown-menu");
            if (menu) menu.classList.toggle("is-open");
            return;
        }
        document.querySelectorAll(".export-dropdown-menu.is-open").forEach(function (m) { m.classList.remove("is-open"); });

        var traceBtn = e.target.closest("[data-trace-e2e]");
        if (traceBtn && !traceBtn.closest(".xray-drawer")) {
            e.preventDefault();
            if (window.PbiFocusLineage) window.PbiFocusLineage(traceBtn.getAttribute("data-trace-e2e"));
            return;
        }
        var mdBtn = e.target.closest("[data-export-measure-md]");
        if (mdBtn) {
            e.preventDefault();
            exportMeasureSpec(mdBtn.getAttribute("data-export-measure-md"), false);
            return;
        }
        var docBtn = e.target.closest("[data-export-measure-doc]");
        if (docBtn) {
            e.preventDefault();
            exportMeasureSpec(docBtn.getAttribute("data-export-measure-doc"), true);
            return;
        }
        var catMdBtn = e.target.closest("[data-export-catalog-md]");
        if (catMdBtn) {
            e.preventDefault();
            var g = window.PBI_E2E_GRAPH || {};
            var mList = g.models || [];
            var dfList = g.dataflows || [];
            var out = ["# Power BI Documentation Catalog Summary", "", "## Semantic Models (" + mList.length + ")", ""];
            mList.forEach(function (m) {
                out.push("- **" + m.name + "** (Workspace: `" + (m.workspace || "-") + "`): " + m.tables + " tables, " + m.measures + " DAX measures");
            });
            if (dfList.length) {
                out.push("", "## Dataflows Gen1 & Gen2 (" + dfList.length + ")", "");
                dfList.forEach(function (d) {
                    out.push("- **" + d.name + "** (" + (d.generation || "Gen1") + ", Workspace: `" + (d.workspace || "-") + "`): " + d.queries + " entities/queries");
                });
            }
            triggerDownload("PBI_Catalog_Summary.md", "text/markdown;charset=utf-8", out.join("\n") + "\n");
            return;
        }

        var expBtn = e.target.closest("[data-details-toggle]");
        if (expBtn) {
            var scopeId = expBtn.getAttribute("data-details-toggle");
            var shouldOpen = expBtn.getAttribute("data-open") === "1";
            var root = document.getElementById(scopeId) || document;
            if (scopeId === "daxCardsContainer") {
                var cBtn = document.querySelector('[data-dax-view="cards"]');
                if (cBtn && !cBtn.classList.contains("active")) cBtn.click();
                var folderDets = root.querySelectorAll("details.dax-folder-details");
                if (folderDets.length) {
                    root.querySelectorAll("details.dax-table-group").forEach(function (g) { g.open = true; });
                    folderDets.forEach(function (d) { d.open = shouldOpen; });
                    return;
                }
            }
            root.querySelectorAll("details").forEach(function (d) { d.open = shouldOpen; });
            return;
        }
        var measureJump = e.target.closest('a[href^="#m-"], a[href^="#measure-"]');
        if (measureJump) {
            var cardsBtn = document.querySelector('[data-dax-view="cards"]');
            if (cardsBtn && !cardsBtn.classList.contains("active")) {
                cardsBtn.click();
            }
            var targetHref = measureJump.getAttribute("href") || "";
            if (targetHref.length > 1) {
                var mEl = document.getElementById(targetHref.slice(1));
                if (mEl) {
                    var fDet = mEl.closest("details.dax-folder-details");
                    if (fDet) fDet.open = true;
                    var tDet = mEl.closest("details.dax-table-group");
                    if (tDet) tDet.open = true;
                }
            }
        }
        var tableJump = e.target.closest('a[href^="#t-"]');
        if (tableJump) {
            var tHref = tableJump.getAttribute("href") || "";
            if (tHref.length > 1) {
                var tEl = document.getElementById(tHref.slice(1));
                if (tEl && tEl.tagName === "DETAILS") tEl.open = true;
            }
        }
        var daxViewBtn = e.target.closest("[data-dax-view]");
        if (daxViewBtn) {
            var v = daxViewBtn.getAttribute("data-dax-view");
            document.querySelectorAll("[data-dax-view]").forEach(function (b) { b.classList.toggle("active", b === daxViewBtn); });
            var cardsBox = document.getElementById("daxCardsContainer");
            var listBox = document.getElementById("daxListContainer");
            if (cardsBox && listBox) {
                cardsBox.style.display = (v === "cards") ? "" : "none";
                listBox.style.display = (v === "list") ? "" : "none";
            }
            return;
        }
        var daxUsageBtn = e.target.closest("[data-dax-usage]");
        if (daxUsageBtn) {
            var mode = daxUsageBtn.getAttribute("data-dax-usage");
            document.querySelectorAll("[data-dax-usage]").forEach(function (b) { b.classList.toggle("active", b === daxUsageBtn); });
            document.querySelectorAll("[data-measure-usage]").forEach(function (el) {
                var u = el.getAttribute("data-measure-usage");
                var show = (mode === "all") || (u === mode);
                el.style.display = show ? "" : "none";
            });
            document.querySelectorAll("details.dax-folder-details").forEach(function (f) {
                var anyVis = Array.from(f.querySelectorAll(".measure-card[data-measure-usage]")).some(function (c) { return c.style.display !== "none"; });
                f.style.display = anyVis ? "" : "none";
                if (mode !== "all" && anyVis) f.open = true;
            });
            return;
        }
        var themeBtn = e.target.closest("[data-toggle-theme]");
        if (themeBtn) {
            var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", cur);
            safeSet("pbidoc-v1-theme", cur);
            return;
        }
        var copyBtn = e.target.closest(".copy-btn[data-copy]");
        if (copyBtn) {
            var pre = copyBtn.parentElement && copyBtn.parentElement.querySelector("pre");
            if (pre && navigator.clipboard) {
                navigator.clipboard.writeText(pre.innerText || pre.textContent || "");
                var old = copyBtn.textContent;
                copyBtn.textContent = "Copied!";
                setTimeout(function () { copyBtn.textContent = old; }, 1200);
            }
            return;
        }
        var tabBtn = e.target.closest(".top-tab[data-tab]");
        if (tabBtn) {
            var target = tabBtn.getAttribute("data-tab");
            document.querySelectorAll(".top-tab").forEach(function (b) { b.classList.toggle("active", b === tabBtn); });
            document.querySelectorAll(".tab-pane").forEach(function (p) { p.classList.toggle("active", p.id === target); });
            if (window.PbiLineageRedrawAll) setTimeout(window.PbiLineageRedrawAll, 40);
        }
    });

    document.addEventListener("keydown", function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            var search = document.querySelector("[data-quick-search]");
            if (search) { e.preventDefault(); search.focus(); search.select(); }
        }
        if (e.key === "Escape") {
            document.querySelectorAll(".lineage-app.is-fullscreen").forEach(function (el) {
                el.classList.remove("is-fullscreen");
                document.body.classList.remove("lin-fullscreen-lock");
                var fb = el.querySelector(".lin-toggle-fs");
                if (fb) fb.textContent = "Fullscreen";
                if (typeof el._lineageRedraw === "function") el._lineageRedraw();
            });
        }
    });
})();
