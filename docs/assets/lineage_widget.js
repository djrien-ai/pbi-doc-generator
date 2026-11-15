
(function () {
    function escHtml(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function initLineageApp(container) {
        var scriptId = container.getAttribute("data-lineage-id");
        var dataEl = document.getElementById(scriptId);
        if (!dataEl) return;
        var graph;
        try { graph = JSON.parse(dataEl.textContent || "{}"); } catch (e) { return; }
        var allNodes = graph.nodes || [];
        var allEdges = graph.edges || [];
        var layers = graph.layers || [];
        if (!allNodes.length) {
            container.innerHTML = '<div style="padding:24px;color:var(--fg-muted)">No lineage objects available for this view.</div>';
            return;
        }

        var isPortfolio = (scriptId === "portfolioLineageData") || (graph.scope === "portfolio");
        var wsOptions = graph.workspaces || [];
        var mdlOptions = graph.models || [];
        var savedOrient = (window.PbiStorage && window.PbiStorage.get("pbidoc-v11-lin-orient")) || "horizontal";

        var state = {
            focusId: graph.defaultFocus || (allNodes[0] && allNodes[0].id) || null,
            hoverId: null,
            layerFilter: "all",
            search: "",
            connectedOnly: true,
            showKpis: !isPortfolio,
            orientation: (savedOrient === "vertical") ? "vertical" : "horizontal",
            wsFilter: "all",
            modelFilter: "all",
            expandedCols: {}
        };

        // Smart default: if portfolio is small (<= 3 models), show full clean estate map right away; if larger, focus primary model cleanly
        if (isPortfolio && mdlOptions.length > 0 && mdlOptions.length <= 4) {
            state.focusId = null;
            state.connectedOnly = false;
        }

        var scopeBadgeHtml = isPortfolio
            ? '<span class="lin-scope-badge" title="High-level cross-workspace architecture">Macro &bull; Portfolio Architecture</span>'
            : '<span class="lin-scope-badge" title="Granular table, column, Power Query, Native SQL &amp; DAX lineage">Micro &bull; Model SQL &amp; DAX Lineage</span>';

        var scopeSelectsHtml = "";
        if (isPortfolio && wsOptions.length > 1) {
            scopeSelectsHtml += '<select class="lin-filter-select lin-ws-select" aria-label="Filter by workspace"><option value="all">All Workspaces (' + wsOptions.length + ')</option>' +
                wsOptions.map(function (w) { return '<option value="' + escHtml(w) + '">' + escHtml(w) + '</option>'; }).join("") + '</select>';
        }
        if (isPortfolio && mdlOptions.length > 1) {
            scopeSelectsHtml += '<select class="lin-filter-select lin-mdl-select" aria-label="Filter by semantic model"><option value="all">All Models (' + mdlOptions.length + ')</option>' +
                mdlOptions.map(function (m) { return '<option value="' + escHtml(m.slug) + '">' + escHtml(m.name) + '</option>'; }).join("") + '</select>';
        }
        var kpiToggleHtml = isPortfolio
            ? '<button type="button" class="lin-btn lin-toggle-kpis" title="Toggle intermediate DAX KPI nodes between Semantic Models and Reports">+ Core KPIs</button>'
            : '';

        container.innerHTML =
            '<div class="lin-left">' +
              '<div class="lin-left-top">' +
                '<input type="search" class="lin-search" placeholder="Search SQL, dataflows, tables, DAX, reports...">' +
                '<div class="lin-layer-pills"></div>' +
              '</div>' +
              '<div class="lin-nav-list"></div>' +
            '</div>' +
            '<div class="lin-center">' +
              '<div class="lin-toolbar">' +
                '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
                  scopeBadgeHtml +
                  '<span class="lin-status"></span>' +
                '</div>' +
                '<div class="lin-toolbar-actions" style="flex-wrap:wrap">' +
                  scopeSelectsHtml +
                  kpiToggleHtml +
                  '<button type="button" class="lin-btn lin-toggle-orient" title="Switch between Horizontal (Left-to-Right) and Vertical (Top-to-Bottom) swimlanes"></button>' +
                  '<button type="button" class="lin-btn lin-toggle-conn"></button>' +
                  '<button type="button" class="lin-btn lin-show-all">Show full map</button>' +
                  '<button type="button" class="lin-btn lin-toggle-fs">Fullscreen</button>' +
                '</div>' +
              '</div>' +
              '<div class="lin-canvas-scroll">' +
                '<svg class="lin-svg"></svg>' +
                '<div class="lin-columns"></div>' +
              '</div>' +
            '</div>' +
            '<div class="lin-right"></div>';

        var searchInput = container.querySelector(".lin-search");
        var pillsWrap = container.querySelector(".lin-layer-pills");
        var navList = container.querySelector(".lin-nav-list");
        var statusEl = container.querySelector(".lin-status");
        var btnConn = container.querySelector(".lin-toggle-conn");
        var btnAll = container.querySelector(".lin-show-all");
        var btnFs = container.querySelector(".lin-toggle-fs");
        var btnOrient = container.querySelector(".lin-toggle-orient");
        var btnKpis = container.querySelector(".lin-toggle-kpis");
        var selWs = container.querySelector(".lin-ws-select");
        var selMdl = container.querySelector(".lin-mdl-select");
        var scrollBox = container.querySelector(".lin-canvas-scroll");
        var svgEl = container.querySelector("svg.lin-svg");
        var colsEl = container.querySelector(".lin-columns");
        var rightEl = container.querySelector(".lin-right");

        var e2eIndex = new Map();
        allNodes.forEach(function (n) {
            if (n.e2eId) e2eIndex.set(n.e2eId, n.id);
        });

        var activeNodes = [];
        var activeEdges = [];
        var nodeMap = new Map();
        var outMap = new Map();
        var inMap = new Map();

        function rebuildActiveGraph() {
            var baseNodes = allNodes.filter(function (n) {
                if (isPortfolio && !state.showKpis && n.kpiDetail && n.id !== state.focusId) return false;
                return true;
            });
            var baseIds = new Set(baseNodes.map(function (n) { return n.id; }));
            var baseEdges = allEdges.filter(function (e) {
                if (!baseIds.has(e.from) || !baseIds.has(e.to)) return false;
                if (isPortfolio && state.showKpis && e.directModelEdge) return false;
                return true;
            });

            // Apply optional Workspace / Model scope filter while preserving upstream/downstream context of matching models
            if (isPortfolio && (state.wsFilter !== "all" || state.modelFilter !== "all")) {
                var tmpOut = new Map();
                var tmpIn = new Map();
                baseNodes.forEach(function (n) { tmpOut.set(n.id, []); tmpIn.set(n.id, []); });
                baseEdges.forEach(function (e) {
                    tmpOut.get(e.from).push(e.to);
                    tmpIn.get(e.to).push(e.from);
                });
                var seeds = baseNodes.filter(function (n) {
                    if (state.modelFilter !== "all") return n.modelSlug === state.modelFilter || n.id === ("mdl:" + state.modelFilter);
                    if (state.wsFilter !== "all") return (n.workspace || "") === state.wsFilter;
                    return true;
                });
                var keep = new Set();
                seeds.forEach(function (s) {
                    keep.add(s.id);
                    var q1 = (tmpIn.get(s.id) || []).slice();
                    while (q1.length) {
                        var u = q1.shift();
                        if (!keep.has(u)) { keep.add(u); (tmpIn.get(u) || []).forEach(function (p) { q1.push(p); }); }
                    }
                    var q2 = (tmpOut.get(s.id) || []).slice();
                    while (q2.length) {
                        var v = q2.shift();
                        if (!keep.has(v)) { keep.add(v); (tmpOut.get(v) || []).forEach(function (nx) { q2.push(nx); }); }
                    }
                });
                activeNodes = baseNodes.filter(function (n) { return keep.has(n.id); });
                activeEdges = baseEdges.filter(function (e) { return keep.has(e.from) && keep.has(e.to); });
            } else {
                activeNodes = baseNodes;
                activeEdges = baseEdges;
            }

            nodeMap = new Map();
            outMap = new Map();
            inMap = new Map();
            activeNodes.forEach(function (n) {
                nodeMap.set(n.id, n);
                outMap.set(n.id, []);
                inMap.set(n.id, []);
            });
            activeEdges.forEach(function (e) {
                if (outMap.has(e.from) && inMap.has(e.to)) {
                    outMap.get(e.from).push(e.to);
                    inMap.get(e.to).push(e.from);
                }
            });
            if (state.focusId && !nodeMap.has(state.focusId)) {
                state.focusId = null;
            }
        }

        function traceSet(startId, adj) {
            var visited = new Set();
            if (!startId || !adj.has(startId)) return visited;
            var queue = (adj.get(startId) || []).slice();
            while (queue.length) {
                var cur = queue.shift();
                if (visited.has(cur) || cur === startId) continue;
                visited.add(cur);
                (adj.get(cur) || []).forEach(function (nxt) {
                    if (!visited.has(nxt)) queue.push(nxt);
                });
            }
            return visited;
        }

        function renderPills() {
            var html = '<button type="button" class="lin-pill ' + (state.layerFilter === "all" ? "active" : "") + '" data-layer="all">All (' + activeNodes.length + ')</button>';
            layers.forEach(function (l) {
                var cnt = activeNodes.filter(function (n) { return n.layer === l.id; }).length;
                if (!cnt) return;
                html += '<button type="button" class="lin-pill ' + (state.layerFilter === l.id ? "active" : "") + '" data-layer="' + escHtml(l.id) + '">' + escHtml(l.label) + ' (' + cnt + ')</button>';
            });
            pillsWrap.innerHTML = html;
        }

        function renderNav() {
            var q = state.search.toLowerCase();
            var filtered = activeNodes.filter(function (n) {
                if (state.layerFilter !== "all" && n.layer !== state.layerFilter) return false;
                if (q && (n.label + " " + (n.sub || "") + " " + (n.detail || "") + " " + (n.sqlCode || "")).toLowerCase().indexOf(q) === -1) return false;
                return true;
            });
            navList.innerHTML = filtered.slice(0, 300).map(function (n) {
                var deg = (inMap.get(n.id) || []).length + (outMap.get(n.id) || []).length;
                return '<button type="button" class="lin-nav-item ' + (state.focusId === n.id ? "active" : "") + '" data-id="' + escHtml(n.id) + '">' +
                    '<span>' + escHtml(n.label) + '</span>' +
                    '<small>' + escHtml(n.layerLabel || n.layer) + (n.sub ? " - " + escHtml(n.sub) : "") + ' (' + deg + ' links)</small>' +
                '</button>';
            }).join("");
        }

        function drawEdges(upstreamSet, downstreamSet) {
            var boxRect = scrollBox.getBoundingClientRect();
            var width = Math.max(scrollBox.scrollWidth, scrollBox.clientWidth);
            var height = Math.max(scrollBox.scrollHeight, scrollBox.clientHeight);
            svgEl.setAttribute("width", String(width));
            svgEl.setAttribute("height", String(height));

            var domNodes = new Map();
            colsEl.querySelectorAll(".lin-node[data-id]").forEach(function (el) {
                domNodes.set(el.getAttribute("data-id"), el);
            });

            var activeTarget = state.focusId || state.hoverId;
            var hovUp = (!state.focusId && state.hoverId) ? traceSet(state.hoverId, inMap) : upstreamSet;
            var hovDown = (!state.focusId && state.hoverId) ? traceSet(state.hoverId, outMap) : downstreamSet;
            var denseUnfocused = !activeTarget && domNodes.size > 34;

            var paths = [];
            var isVert = state.orientation === "vertical";
            activeEdges.forEach(function (e) {
                if (!domNodes.has(e.from) || !domNodes.has(e.to)) return;
                var a = domNodes.get(e.from).getBoundingClientRect();
                var b = domNodes.get(e.to).getBoundingClientRect();

                var active = !activeTarget ||
                    (e.from === activeTarget || e.to === activeTarget) ||
                    (hovUp.has(e.from) && (hovUp.has(e.to) || e.to === activeTarget)) ||
                    (hovDown.has(e.to) && (hovDown.has(e.from) || e.from === activeTarget));

                var stroke;
                var sw;
                if (activeTarget) {
                    stroke = active ? (hovUp.has(e.from) || e.to === activeTarget ? "#0f766e" : "#0b63ce") : "rgba(148,163,184,0.14)";
                    sw = active ? "2.1" : "1.0";
                } else if (denseUnfocused) {
                    stroke = "rgba(148,163,184,0.13)";
                    sw = "1.0";
                } else {
                    stroke = "rgba(11,99,206,0.34)";
                    sw = "1.35";
                }

                var dAttr;
                if (isVert) {
                    var vx1 = a.left + a.width / 2 - boxRect.left + scrollBox.scrollLeft;
                    var vy1 = a.bottom - boxRect.top + scrollBox.scrollTop;
                    var vx2 = b.left + b.width / 2 - boxRect.left + scrollBox.scrollLeft;
                    var vy2 = b.top - boxRect.top + scrollBox.scrollTop;
                    if (vy2 < vy1) {
                        vy1 = a.top - boxRect.top + scrollBox.scrollTop;
                        vy2 = b.bottom - boxRect.top + scrollBox.scrollTop;
                    }
                    var dy = Math.max(22, Math.abs(vy2 - vy1) * 0.45);
                    dAttr = 'M ' + vx1.toFixed(1) + ' ' + vy1.toFixed(1) + ' C ' + vx1.toFixed(1) + ' ' + (vy1 + dy).toFixed(1) + ', ' + vx2.toFixed(1) + ' ' + (vy2 - dy).toFixed(1) + ', ' + vx2.toFixed(1) + ' ' + vy2.toFixed(1);
                } else {
                    var x1 = a.right - boxRect.left + scrollBox.scrollLeft;
                    var y1 = a.top + a.height / 2 - boxRect.top + scrollBox.scrollTop;
                    var x2 = b.left - boxRect.left + scrollBox.scrollLeft;
                    var y2 = b.top + b.height / 2 - boxRect.top + scrollBox.scrollTop;
                    if (x2 < x1) {
                        x1 = a.left - boxRect.left + scrollBox.scrollLeft;
                        x2 = b.right - boxRect.left + scrollBox.scrollLeft;
                    }
                    var dx = Math.max(28, Math.abs(x2 - x1) * 0.45);
                    dAttr = 'M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C ' + (x1 + dx).toFixed(1) + ' ' + y1.toFixed(1) + ', ' + (x2 - dx).toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1);
                }
                paths.push('<path d="' + dAttr + '" fill="none" stroke="' + stroke + '" stroke-width="' + sw + '"/>');
            });
            svgEl.innerHTML = paths.join("");
        }

        function renderCanvasAndInspector() {
            var up = traceSet(state.focusId, inMap);
            var down = traceSet(state.focusId, outMap);
            var connected = new Set([state.focusId]);
            up.forEach(function (x) { connected.add(x); });
            down.forEach(function (x) { connected.add(x); });

            colsEl.classList.toggle("is-vertical", state.orientation === "vertical");
            if (btnOrient) {
                btnOrient.textContent = state.orientation === "vertical" ? "Layout: Vertical" : "Layout: Horizontal";
                btnOrient.classList.toggle("active", state.orientation === "vertical");
            }
            if (btnKpis) {
                btnKpis.textContent = state.showKpis ? "Hide Core KPIs" : "+ Show Core KPIs";
                btnKpis.classList.toggle("active", state.showKpis);
            }
            var hasFocus = !!(state.focusId && nodeMap.has(state.focusId));
            btnConn.textContent = state.connectedOnly ? "Filter: Connected path" : "Filter: All objects";
            btnConn.classList.toggle("active", hasFocus && state.connectedOnly);
            btnConn.disabled = !hasFocus;
            btnConn.title = hasFocus ? "Toggle between connected path and all objects" : "Click any node first to filter its connected path";
            btnAll.disabled = !hasFocus && !state.connectedOnly;

            if (hasFocus) {
                var fn = nodeMap.get(state.focusId);
                statusEl.innerHTML = 'Focused: <b>' + escHtml(fn.label) + '</b> (' + up.size + ' upstream, ' + down.size + ' downstream) ' +
                    '<button type="button" class="lin-btn lin-clear-focus" style="padding:1px 7px;font-size:11px;margin-left:4px">&times; Clear</button>';
            } else {
                statusEl.textContent = activeNodes.length + " objects, " + activeEdges.length + " links (hover or click any card to trace)";
            }

            var capPerCol = state.focusId ? 85 : 18;
            var colsHtml = [];
            layers.forEach(function (layer) {
                var colNodes = activeNodes.filter(function (n) {
                    if (n.layer !== layer.id) return false;
                    if (state.focusId && state.connectedOnly && !connected.has(n.id)) return false;
                    return true;
                });
                if (!colNodes.length) return;
                var isExp = !!state.expandedCols[layer.id];
                var shownNodes = isExp ? colNodes.slice(0, 120) : colNodes.slice(0, capPerCol);
                var cards = shownNodes.map(function (n) {
                    var cls = "lin-node";
                    if (state.focusId) {
                        if (n.id === state.focusId) cls += " is-focus";
                        else if (up.has(n.id)) cls += " is-upstream";
                        else if (down.has(n.id)) cls += " is-downstream";
                        else cls += " is-muted";
                    }
                    return '<div class="' + cls + '" data-id="' + escHtml(n.id) + '">' +
                        '<div class="n-title">' + escHtml(n.label) + '</div>' +
                        (n.sub ? '<div class="n-sub">' + escHtml(n.sub) + '</div>' : '') +
                    '</div>';
                }).join("");
                var moreBtn = "";
                if (!isExp && colNodes.length > capPerCol) {
                    moreBtn = '<button type="button" class="lin-btn" style="margin-top:2px;text-align:center" data-expand-col="' + escHtml(layer.id) + '">+ Show ' + (colNodes.length - capPerCol) + ' more</button>';
                } else if (isExp && colNodes.length > capPerCol) {
                    moreBtn = '<button type="button" class="lin-btn" style="margin-top:2px;text-align:center" data-collapse-col="' + escHtml(layer.id) + '">Show fewer</button>';
                }
                colsHtml.push('<div class="lin-col"><div class="lin-col-hdr">' + escHtml(layer.label) + ' (' + colNodes.length + ')</div>' + cards + moreBtn + '</div>');
            });
            colsEl.innerHTML = colsHtml.join("");

            if (state.focusId && nodeMap.has(state.focusId)) {
                var cur = nodeMap.get(state.focusId);
                var directIn = (inMap.get(cur.id) || []).map(function (id) { return nodeMap.get(id); }).filter(Boolean);
                var directOut = (outMap.get(cur.id) || []).map(function (id) { return nodeMap.get(id); }).filter(Boolean);
                var insp = '<span class="badge badge-accent">' + escHtml(cur.layerLabel || cur.layer) + '</span>' +
                    '<h4>' + escHtml(cur.label) + '</h4>';
                if (cur.sub) insp += '<div class="lin-kv">' + escHtml(cur.sub) + '</div>';
                if (cur.detail) insp += '<div style="font-size:12px">' + escHtml(cur.detail) + '</div>';
                if (cur.href || cur.xrayId || cur.e2eMeasureId) {
                    insp += '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">';
                    if (cur.href) {
                        insp += '<a class="dep-chip" style="border-color:var(--accent);color:var(--accent);font-weight:600;padding:4px 9px" href="' + escHtml(cur.href) + '">' + escHtml(cur.hrefLabel || "Jump to documentation") + ' &rarr;</a>';
                    }
                    if (cur.xrayId) {
                        insp += '<button type="button" class="xray-trigger-btn" data-open-xray="' + escHtml(cur.xrayId) + '">' + escHtml(cur.xrayLabel || "Inspect Layout") + ' &rarr;</button>';
                    }
                    if (cur.e2eMeasureId) {
                        insp += '<button type="button" class="lin-btn" data-export-measure-md="' + escHtml(cur.e2eMeasureId) + '" title="Download full Measure-to-SQL lineage spec as Markdown">Measure Doc (.md)</button>';
                        insp += '<button type="button" class="lin-btn" data-export-measure-doc="' + escHtml(cur.e2eMeasureId) + '" title="Download formatted Word specification">Word (.doc)</button>';
                    }
                    insp += '</div>';
                }
                if (cur.sqlCode) {
                    insp += '<div class="lin-kv" style="margin-top:2px"><b>Formatted Native SQL</b></div>' +
                        '<div class="code-block" style="font-size:11px;padding:8px 54px 8px 10px"><button type="button" class="copy-btn" data-copy="1">Copy</button><pre>' + escHtml(cur.sqlCode) + '</pre></div>';
                }
                if (cur.stepsSummary && cur.stepsSummary.length) {
                    insp += '<div class="lin-kv" style="margin-top:2px"><b>Power Query Steps (' + cur.stepsSummary.length + ')</b></div>' +
                        '<div style="display:flex;flex-direction:column;gap:3px;font-size:11px">' +
                        cur.stepsSummary.slice(0, 8).map(function (st, idx) {
                            return '<div style="padding:3px 6px;border-radius:5px;background:var(--surface-alt);border:1px solid var(--border)"><b>' + (idx + 1) + '. ' + escHtml(st.name) + '</b>: ' + escHtml(st.summary) + '</div>';
                        }).join("") + '</div>';
                }
                if (cur.code) {
                    insp += '<div class="code-block" style="font-size:11.5px;padding:8px 54px 8px 10px"><button type="button" class="copy-btn" data-copy="1">Copy</button><pre>' + escHtml(cur.code) + '</pre></div>';
                }
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Upstream (' + directIn.length + ')</b></div><div class="lin-list">' +
                    (directIn.length ? directIn.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (root source)</span>') +
                    '</div>';
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Downstream (' + directOut.length + ')</b></div><div class="lin-list">' +
                    (directOut.length ? directOut.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (leaf consumer)</span>') +
                    '</div>';
                rightEl.innerHTML = insp;
            } else {
                var hintScope = isPortfolio
                    ? "Portfolio Architecture view hides intermediate DAX KPIs by default so cross-workspace Source &rarr; Dataflow &rarr; Semantic Model &rarr; Report chains stay clean. Click any model or toggle <b>+ Show Core KPIs</b> to drill deeper."
                    : "Click any source, SQL query, dataflow Gen1/Gen2 entity, table, column, DAX measure, or thin report to trace its upstream origins and downstream impact in real time.";
                rightEl.innerHTML = '<h4>Interactive Live Lineage</h4><div class="lin-kv">' + hintScope + '</div>';
            }

            window.requestAnimationFrame(function () { drawEdges(up, down); });
        }

        function refreshAll() {
            rebuildActiveGraph();
            renderPills();
            renderNav();
            renderCanvasAndInspector();
        }

        container._focusNode = function (targetId) {
            var resolved = e2eIndex.get(targetId) || targetId;
            var rawMatch = allNodes.some(function (n) { return n.id === resolved; });
            if (!rawMatch) return false;
            var targetObj = allNodes.find(function (n) { return n.id === resolved; });
            if (targetObj && targetObj.kpiDetail && !state.showKpis) {
                state.showKpis = true;
            }
            state.wsFilter = "all";
            state.modelFilter = "all";
            if (selWs) selWs.value = "all";
            if (selMdl) selMdl.value = "all";
            state.focusId = resolved;
            state.connectedOnly = true;
            state.layerFilter = "all";
            refreshAll();
            return true;
        };

        searchInput.addEventListener("input", function () { state.search = searchInput.value || ""; renderNav(); });
        pillsWrap.addEventListener("click", function (e) {
            var b = e.target.closest("button[data-layer]");
            if (!b) return;
            state.layerFilter = b.getAttribute("data-layer");
            renderPills(); renderNav();
        });
        navList.addEventListener("click", function (e) {
            var b = e.target.closest("button[data-id]");
            if (!b) return;
            state.focusId = b.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        colsEl.addEventListener("click", function (e) {
            var expCol = e.target.closest("[data-expand-col]");
            if (expCol) {
                state.expandedCols[expCol.getAttribute("data-expand-col")] = true;
                renderCanvasAndInspector();
                return;
            }
            var colCol = e.target.closest("[data-collapse-col]");
            if (colCol) {
                state.expandedCols[colCol.getAttribute("data-collapse-col")] = false;
                renderCanvasAndInspector();
                return;
            }
            var card = e.target.closest(".lin-node[data-id]");
            if (!card) return;
            state.focusId = card.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        colsEl.addEventListener("mouseover", function (e) {
            if (state.focusId) return;
            var card = e.target.closest(".lin-node[data-id]");
            var nid = card ? card.getAttribute("data-id") : null;
            if (nid !== state.hoverId) {
                state.hoverId = nid;
                drawEdges(new Set(), new Set());
            }
        });
        colsEl.addEventListener("mouseleave", function () {
            if (!state.focusId && state.hoverId) {
                state.hoverId = null;
                drawEdges(new Set(), new Set());
            }
        });
        rightEl.addEventListener("click", function (e) {
            var b = e.target.closest(".lin-jump[data-id]");
            if (!b) return;
            state.focusId = b.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        statusEl.addEventListener("click", function (e) {
            if (e.target.closest(".lin-clear-focus")) {
                state.focusId = null;
                state.connectedOnly = false;
                renderNav();
                renderCanvasAndInspector();
            }
        });
        btnConn.addEventListener("click", function () { if (!state.focusId) return; state.connectedOnly = !state.connectedOnly; renderCanvasAndInspector(); });
        btnAll.addEventListener("click", function () { state.focusId = null; state.connectedOnly = false; renderNav(); renderCanvasAndInspector(); });
        if (btnOrient) {
            btnOrient.addEventListener("click", function () {
                state.orientation = (state.orientation === "vertical") ? "horizontal" : "vertical";
                if (window.PbiStorage) window.PbiStorage.set("pbidoc-v11-lin-orient", state.orientation);
                renderCanvasAndInspector();
            });
        }
        if (btnKpis) {
            btnKpis.addEventListener("click", function () {
                state.showKpis = !state.showKpis;
                refreshAll();
            });
        }
        if (selWs) {
            selWs.addEventListener("change", function () {
                state.wsFilter = selWs.value || "all";
                state.focusId = null;
                refreshAll();
            });
        }
        if (selMdl) {
            selMdl.addEventListener("change", function () {
                state.modelFilter = selMdl.value || "all";
                state.focusId = (state.modelFilter !== "all") ? ("mdl:" + state.modelFilter) : null;
                state.connectedOnly = (state.modelFilter !== "all");
                refreshAll();
            });
        }
        btnFs.addEventListener("click", function () {
            var isFs = container.classList.toggle("is-fullscreen");
            document.body.classList.toggle("lin-fullscreen-lock", isFs);
            btnFs.textContent = isFs ? "Exit Fullscreen" : "Fullscreen";
            setTimeout(refreshAll, 35);
        });
        scrollBox.addEventListener("scroll", function () { drawEdges(traceSet(state.focusId, inMap), traceSet(state.focusId, outMap)); });
        window.addEventListener("resize", function () { drawEdges(traceSet(state.focusId, inMap), traceSet(state.focusId, outMap)); });

        container._lineageRedraw = refreshAll;
        refreshAll();
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".lineage-app[data-lineage-id]").forEach(initLineageApp);
    });
    window.PbiLineageRedrawAll = function () {
        document.querySelectorAll(".lineage-app").forEach(function (el) {
            if (typeof el._lineageRedraw === "function") el._lineageRedraw();
        });
    };
    window.PbiFocusLineage = function (targetId) {
        if (!targetId) return;
        var tabBtn = document.querySelector('.top-tab[data-tab="tab-lineage"]');
        if (tabBtn && !tabBtn.classList.contains("active")) {
            tabBtn.click();
        }
        var secLin = document.getElementById("sec-lineage");
        var matched = false;
        document.querySelectorAll(".lineage-app").forEach(function (el) {
            if (!matched && typeof el._focusNode === "function") {
                matched = el._focusNode(targetId);
                if (matched) {
                    setTimeout(function () {
                        (secLin || el).scrollIntoView({ behavior: "smooth", block: "start" });
                    }, 40);
                }
            }
        });
    };
})();
