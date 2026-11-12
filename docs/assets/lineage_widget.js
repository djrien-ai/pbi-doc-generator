
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
        var nodes = graph.nodes || [];
        var edges = graph.edges || [];
        var layers = graph.layers || [];
        if (!nodes.length) {
            container.innerHTML = '<div style="padding:24px;color:var(--fg-muted)">No lineage objects available for this view.</div>';
            return;
        }

        var nodeMap = new Map();
        var outMap = new Map();
        var inMap = new Map();
        nodes.forEach(function (n) {
            nodeMap.set(n.id, n);
            outMap.set(n.id, []);
            inMap.set(n.id, []);
        });
        edges.forEach(function (e) {
            if (outMap.has(e.from) && inMap.has(e.to)) {
                outMap.get(e.from).push(e.to);
                inMap.get(e.to).push(e.from);
            }
        });

        var state = {
            focusId: graph.defaultFocus || (nodes[0] && nodes[0].id) || null,
            layerFilter: "all",
            search: "",
            connectedOnly: true
        };

        container.innerHTML =
            '<div class="lin-left">' +
              '<div class="lin-left-top">' +
                '<input type="search" class="lin-search" placeholder="Search sources, tables, DAX, reports...">' +
                '<div class="lin-layer-pills"></div>' +
              '</div>' +
              '<div class="lin-nav-list"></div>' +
            '</div>' +
            '<div class="lin-center">' +
              '<div class="lin-toolbar">' +
                '<span class="lin-status"></span>' +
                '<div class="lin-toolbar-actions">' +
                  '<button type="button" class="lin-btn lin-toggle-conn"></button>' +
                  '<button type="button" class="lin-btn lin-show-all">Show full graph</button>' +
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
        var scrollBox = container.querySelector(".lin-canvas-scroll");
        var svgEl = container.querySelector("svg.lin-svg");
        var colsEl = container.querySelector(".lin-columns");
        var rightEl = container.querySelector(".lin-right");

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
            var html = '<button type="button" class="lin-pill ' + (state.layerFilter === "all" ? "active" : "") + '" data-layer="all">All (' + nodes.length + ')</button>';
            layers.forEach(function (l) {
                var cnt = nodes.filter(function (n) { return n.layer === l.id; }).length;
                if (!cnt) return;
                html += '<button type="button" class="lin-pill ' + (state.layerFilter === l.id ? "active" : "") + '" data-layer="' + escHtml(l.id) + '">' + escHtml(l.label) + ' (' + cnt + ')</button>';
            });
            pillsWrap.innerHTML = html;
        }

        function renderNav() {
            var q = state.search.toLowerCase();
            var filtered = nodes.filter(function (n) {
                if (state.layerFilter !== "all" && n.layer !== state.layerFilter) return false;
                if (q && (n.label + " " + (n.sub || "") + " " + (n.detail || "")).toLowerCase().indexOf(q) === -1) return false;
                return true;
            });
            navList.innerHTML = filtered.slice(0, 250).map(function (n) {
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

            var paths = [];
            edges.forEach(function (e) {
                if (!domNodes.has(e.from) || !domNodes.has(e.to)) return;
                var a = domNodes.get(e.from).getBoundingClientRect();
                var b = domNodes.get(e.to).getBoundingClientRect();
                var x1 = a.right - boxRect.left + scrollBox.scrollLeft;
                var y1 = a.top + a.height / 2 - boxRect.top + scrollBox.scrollTop;
                var x2 = b.left - boxRect.left + scrollBox.scrollLeft;
                var y2 = b.top + b.height / 2 - boxRect.top + scrollBox.scrollTop;
                if (x2 < x1) {
                    x1 = a.left - boxRect.left + scrollBox.scrollLeft;
                    x2 = b.right - boxRect.left + scrollBox.scrollLeft;
                }
                var dx = Math.max(28, Math.abs(x2 - x1) * 0.45);
                var active = !state.focusId ||
                    (e.from === state.focusId || e.to === state.focusId) ||
                    (upstreamSet.has(e.from) && (upstreamSet.has(e.to) || e.to === state.focusId)) ||
                    (downstreamSet.has(e.to) && (downstreamSet.has(e.from) || e.from === state.focusId));
                var stroke = active ? (upstreamSet.has(e.from) || e.to === state.focusId ? "#0f766e" : "#0b63ce") : "rgba(148,163,184,0.22)";
                var sw = active && state.focusId ? "2.1" : "1.2";
                paths.push('<path d="M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C ' + (x1 + dx).toFixed(1) + ' ' + y1.toFixed(1) + ', ' + (x2 - dx).toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + '" fill="none" stroke="' + stroke + '" stroke-width="' + sw + '"/>');
            });
            svgEl.innerHTML = paths.join("");
        }

        function renderCanvasAndInspector() {
            var up = traceSet(state.focusId, inMap);
            var down = traceSet(state.focusId, outMap);
            var connected = new Set([state.focusId]);
            up.forEach(function (x) { connected.add(x); });
            down.forEach(function (x) { connected.add(x); });

            btnConn.textContent = state.connectedOnly ? "Filter: Connected path" : "Filter: All objects";
            btnConn.classList.toggle("active", state.connectedOnly);

            if (state.focusId && nodeMap.has(state.focusId)) {
                var fn = nodeMap.get(state.focusId);
                statusEl.innerHTML = 'Focused: <b>' + escHtml(fn.label) + '</b> (' + up.size + ' upstream, ' + down.size + ' downstream)';
            } else {
                statusEl.textContent = "Showing full lineage map (" + nodes.length + " objects, " + edges.length + " links)";
            }

            var colsHtml = [];
            layers.forEach(function (layer) {
                var colNodes = nodes.filter(function (n) {
                    if (n.layer !== layer.id) return false;
                    if (state.focusId && state.connectedOnly && !connected.has(n.id)) return false;
                    return true;
                });
                if (!colNodes.length) return;
                var cards = colNodes.slice(0, 80).map(function (n) {
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
                colsHtml.push('<div class="lin-col"><div class="lin-col-hdr">' + escHtml(layer.label) + ' (' + colNodes.length + ')</div>' + cards + '</div>');
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
                if (cur.href) {
                    insp += '<a class="dep-chip" style="border-color:var(--accent);color:var(--accent);font-weight:600;padding:5px 10px" href="' + escHtml(cur.href) + '">' + escHtml(cur.hrefLabel || "Jump to documentation") + ' -></a>';
                }
                if (cur.code) {
                    insp += '<div class="code-block" style="font-size:11.5px;padding:8px 10px"><pre>' + escHtml(cur.code) + '</pre></div>';
                }
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Upstream (' + directIn.length + ')</b></div><div class="lin-list">' +
                    (directIn.length ? directIn.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (root source)</span>') +
                    '</div>';
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Downstream (' + directOut.length + ')</b></div><div class="lin-list">' +
                    (directOut.length ? directOut.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (leaf consumer)</span>') +
                    '</div>';
                rightEl.innerHTML = insp;
            } else {
                rightEl.innerHTML = '<h4>Interactive Live Lineage</h4><div class="lin-kv">Click any source, table, column, DAX measure, or report to trace its upstream origins and downstream impact in real time.</div>';
            }

            window.requestAnimationFrame(function () { drawEdges(up, down); });
        }

        function refreshAll() { renderPills(); renderNav(); renderCanvasAndInspector(); }

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
            var card = e.target.closest(".lin-node[data-id]");
            if (!card) return;
            state.focusId = card.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        rightEl.addEventListener("click", function (e) {
            var b = e.target.closest(".lin-jump[data-id]");
            if (!b) return;
            state.focusId = b.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        btnConn.addEventListener("click", function () { state.connectedOnly = !state.connectedOnly; renderCanvasAndInspector(); });
        btnAll.addEventListener("click", function () { state.focusId = null; state.connectedOnly = false; renderNav(); renderCanvasAndInspector(); });
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
})();
