
(function () {
    function ready(fn) {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
        else fn();
    }
    function decodeHtml(value) {
        var txt = document.createElement("textarea");
        txt.innerHTML = value || "";
        return txt.value;
    }
    function norm(value) {
        return decodeHtml(value || "").replace(/\s+/g, " ").replace(/^['"]|['"]$/g, "").trim();
    }
    function parseMermaidSource(source) {
        var nodes = new Map();
        var edges = [];
        String(source || "").split(/\r?\n/).forEach(function (raw) {
            var line = raw.replace(/%%.*$/, "").trim();
            if (!line || /^(graph|flowchart|classDef|class\s|style\s|linkStyle\s|subgraph\b|end\b)/i.test(line)) return;
            var edgeMatch = line.match(/^([A-Za-z0-9_]+)\s*(?:-->|---|-\.->|==>|--x|--o|<-->|<--|--)\s*(?:\|\s*["']?([^|"']*?)["']?\s*\|\s*)?([A-Za-z0-9_]+)/);
            if (edgeMatch) {
                var from = edgeMatch[1], label = norm(edgeMatch[2] || ""), to = edgeMatch[3];
                if (!nodes.has(from)) nodes.set(from, { id: from, label: from });
                if (!nodes.has(to)) nodes.set(to, { id: to, label: to });
                edges.push({ key: from + "->" + to + "#" + edges.length, index: edges.length, from: from, to: to, label: label });
                return;
            }
            var nodeMatch = line.match(/^([A-Za-z0-9_]+)\s*\[\s*["']?([^\]"']+?)["']?\s*\]/);
            if (nodeMatch) {
                nodes.set(nodeMatch[1], { id: nodeMatch[1], label: norm(nodeMatch[2] || nodeMatch[1]) });
            }
        });
        return { nodes: Array.from(nodes.values()), edges: edges };
    }
    function prepareShells() {
        var pres = Array.from(document.querySelectorAll("pre.mermaid"));
        pres.forEach(function (pre, index) {
            if (pre.closest(".mermaid-shell")) return;
            pre.dataset.mermaidSource = pre.textContent || pre.innerText || "";
            var shell = document.createElement("div");
            shell.className = "mermaid-shell";
            var toolbar = document.createElement("div");
            toolbar.className = "mermaid-toolbar";
            toolbar.innerHTML = '<span class="mermaid-hint">Hover to preview relationships. Click a table to pin connected paths; drag canvas to pan.</span>' +
                '<button type="button" data-action="zoom-out" title="Zoom out">-</button>' +
                '<button type="button" data-action="zoom-reset" title="Fit to width">Fit</button>' +
                '<button type="button" data-action="zoom-in" title="Zoom in">+</button>' +
                '<button type="button" data-action="fullscreen" title="Toggle fullscreen">Fullscreen</button>' +
                '<button type="button" data-action="clear" title="Clear pinned tables">Reset highlight</button>';
            var viewport = document.createElement("div");
            viewport.className = "mermaid-viewport";
            viewport.dataset.diagramIndex = String(index);
            pre.parentNode.insertBefore(shell, pre);
            shell.appendChild(toolbar);
            shell.appendChild(viewport);
            viewport.appendChild(pre);
        });
        return pres;
    }
    function findNodeElement(svg, node) {
        var candidates = Array.from(svg.querySelectorAll("g.node, g[class*='node']"));
        var match = candidates.find(function (el) {
            var id = el.id || "";
            return id.indexOf("flowchart-" + node.id + "-") !== -1 || id === node.id;
        });
        if (match) return match;
        var expected = norm(node.label || node.id);
        return candidates.find(function (el) { return norm(el.textContent).indexOf(expected) !== -1; }) || null;
    }
    function findEdgeElements(svg, edge) {
        var fromClass = "LS-" + edge.from, toClass = "LE-" + edge.to;
        var edgeCandidates = Array.from(svg.querySelectorAll("g.edgePath, .edgePath, path.flowchart-link, .flowchart-link"));
        var labelCandidates = Array.from(svg.querySelectorAll("g.edgeLabel"));
        var paths = edgeCandidates.filter(function (el) { return el.classList && el.classList.contains(fromClass) && el.classList.contains(toClass); });
        var labels = labelCandidates.filter(function (el) { return el.classList && el.classList.contains(fromClass) && el.classList.contains(toClass); });
        if (!paths.length) {
            paths = edgeCandidates.filter(function (el) {
                var id = el.id || "", cls = el.getAttribute("class") || "";
                return (id.indexOf(edge.from) !== -1 && id.indexOf(edge.to) !== -1) || (cls.indexOf(edge.from) !== -1 && cls.indexOf(edge.to) !== -1);
            });
        }
        if (!labels.length && typeof edge.index === "number" && labelCandidates[edge.index]) labels = [labelCandidates[edge.index]];
        return {
            paths: Array.from(new Set(paths.map(function (el) { return el.closest("g.edgePath") || el; }))),
            labels: Array.from(new Set(labels))
        };
    }
    function setBaseSvgSize(svg, viewport) {
        var vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
        var baseWidth = vb.length === 4 && vb[2] ? vb[2] : (svg.getBoundingClientRect().width || 900);
        svg.dataset.baseWidth = String(baseWidth);
        var avail = Math.max(260, viewport.clientWidth - 36);
        var fit = Math.max(0.15, Math.min(1.0, avail / baseWidth));
        svg.dataset.zoom = String(fit);
        svg.style.width = Math.max(220, Math.floor(baseWidth * fit)) + "px";
    }
    function applyZoom(svg, factor) {
        var baseWidth = Number(svg.dataset.baseWidth || 900);
        var zoom = Math.max(0.35, Math.min(3.0, Number(svg.dataset.zoom || "1") * factor));
        svg.dataset.zoom = String(zoom);
        svg.style.width = Math.max(260, baseWidth * zoom) + "px";
    }
    function enablePanning(viewport) {
        var dragging = false, sx = 0, sy = 0, sl = 0, st = 0;
        viewport.addEventListener("mousedown", function (e) {
            if (e.button !== 0 || (e.target.closest && e.target.closest(".node, .edgePath, .edgeLabel, button"))) return;
            dragging = true; sx = e.pageX; sy = e.pageY; sl = viewport.scrollLeft; st = viewport.scrollTop;
            viewport.classList.add("is-panning"); e.preventDefault();
        });
        window.addEventListener("mousemove", function (e) {
            if (!dragging) return;
            viewport.scrollLeft = sl - (e.pageX - sx);
            viewport.scrollTop = st - (e.pageY - sy);
        });
        window.addEventListener("mouseup", function () { dragging = false; viewport.classList.remove("is-panning"); });
    }
    function setupDiagram(shell) {
        if (!shell || shell.dataset.ready === "1") return;
        var pre = shell.querySelector("pre.mermaid"), viewport = shell.querySelector(".mermaid-viewport"), toolbar = shell.querySelector(".mermaid-toolbar"), svg = shell.querySelector("svg");
        if (!pre || !viewport || !toolbar || !svg) return;
        shell.dataset.ready = "1";
        svg.classList.add("mermaid-interactive");
        setBaseSvgSize(svg, viewport);
        enablePanning(viewport);
        var graph = parseMermaidSource(pre.dataset.mermaidSource || "");
        var nodeById = new Map(), edgeByKey = new Map(), selectedNodes = new Set(), selectedEdges = new Set(), hoverNode = null, hoverEdge = null;
        graph.nodes.forEach(function (n) {
            var el = findNodeElement(svg, n);
            if (!el) return;
            n.el = el; nodeById.set(n.id, n);
        });
        graph.edges.forEach(function (e) {
            e.elements = findEdgeElements(svg, e);
            edgeByKey.set(e.key, e);
        });
        function updateView() {
            svg.querySelectorAll(".is-selected, .is-related").forEach(function (el) { el.classList.remove("is-selected", "is-related"); });
            var aNodes = new Set(Array.from(selectedNodes)), aEdges = new Set(Array.from(selectedEdges));
            if (hoverNode) aNodes.add(hoverNode);
            if (hoverEdge) aEdges.add(hoverEdge);
            aNodes.forEach(function (nid) {
                graph.edges.forEach(function (e) { if (e.from === nid || e.to === nid) aEdges.add(e.key); });
            });
            var relNodes = new Set(Array.from(aNodes));
            aEdges.forEach(function (ek) {
                var e = edgeByKey.get(ek);
                if (e) { relNodes.add(e.from); relNodes.add(e.to); }
            });
            var hasActive = aNodes.size > 0 || aEdges.size > 0;
            svg.classList.toggle("is-dimmed", hasActive);
            relNodes.forEach(function (nid) {
                var n = nodeById.get(nid);
                if (n && n.el) n.el.classList.add(aNodes.has(nid) ? "is-selected" : "is-related");
            });
            aEdges.forEach(function (ek) {
                var e = edgeByKey.get(ek);
                if (e) e.elements.paths.concat(e.elements.labels).forEach(function (el) { el.classList.add(selectedEdges.has(ek) ? "is-selected" : "is-related"); });
            });
        }
        nodeById.forEach(function (n) {
            n.el.addEventListener("mouseenter", function () { hoverNode = n.id; updateView(); });
            n.el.addEventListener("mouseleave", function () { hoverNode = null; updateView(); });
            n.el.addEventListener("click", function (ev) {
                ev.preventDefault(); ev.stopPropagation();
                if (selectedNodes.has(n.id)) selectedNodes.delete(n.id); else selectedNodes.add(n.id);
                updateView();
            });
        });
        toolbar.addEventListener("click", function (ev) {
            var btn = ev.target.closest("button[data-action]");
            if (!btn) return;
            var act = btn.dataset.action;
            if (act === "zoom-in") applyZoom(svg, 1.2);
            if (act === "zoom-out") applyZoom(svg, 1 / 1.2);
            if (act === "zoom-reset") setBaseSvgSize(svg, viewport);
            if (act === "fullscreen") {
                shell.classList.toggle("is-fallback-fullscreen");
                document.body.classList.toggle("mermaid-fallback-fullscreen", shell.classList.contains("is-fallback-fullscreen"));
                setBaseSvgSize(svg, viewport);
            }
            if (act === "clear") { selectedNodes.clear(); selectedEdges.clear(); hoverNode = null; hoverEdge = null; updateView(); }
        });
    }
    ready(function () {
        if (typeof mermaid === "undefined") return;
        var nodes = prepareShells();
        if (!nodes.length) return;
        mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict", flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis" } });
        var done = function () { window.requestAnimationFrame(function () { document.querySelectorAll(".mermaid-shell").forEach(setupDiagram); }); };
        if (typeof mermaid.run === "function") mermaid.run({ nodes: nodes, suppressErrors: true }).then(done).catch(done);
        else if (typeof mermaid.init === "function") mermaid.init(undefined, nodes, done);
    });
})();
