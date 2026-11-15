
(function () {
    function escHtml(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function midTrunc(s, maxLen) {
        s = String(s || "");
        if (s.length <= maxLen) return s;
        var keep = Math.max(10, maxLen - 3);
        var head = Math.floor(keep * 0.56);
        return s.slice(0, head) + "..." + s.slice(-(keep - head));
    }

    function initStarApp(shell) {
        var scriptId = shell.getAttribute("data-star-id");
        var dataEl = document.getElementById(scriptId);
        if (!dataEl) return;
        var model;
        try { model = JSON.parse(dataEl.textContent || "{}"); } catch (e) { return; }
        var tables = model.tables || [];
        var rels = model.relationships || [];
        var facts = model.facts || [];
        if (!tables.length) {
            shell.innerHTML = '<div style="padding:18px;color:var(--fg-muted)">No tables available in this model.</div>';
            return;
        }

        var tblByName = new Map();
        tables.forEach(function (t) { tblByName.set(t.name, t); });

        var defaultFocus = "all";
        if (facts.length > 0 && (facts.length > 1 || tables.length > 10)) {
            defaultFocus = "fact:" + facts[0];
        } else if (facts.length === 1 && rels.length > 0) {
            defaultFocus = "fact:" + facts[0];
        }

        var state = {
            mode: defaultFocus,
            activeTable: null,
            search: "",
            zoom: 1.0
        };

        shell.innerHTML =
            '<div class="star-toolbar">' +
              '<div class="star-focus-pills"></div>' +
              '<div class="star-actions">' +
                '<input type="search" class="star-search-input" placeholder="Filter tables..." style="display:none">' +
                '<button type="button" class="lin-btn" data-zoom="0.9">90%</button>' +
                '<button type="button" class="lin-btn active" data-zoom="1">100%</button>' +
                '<button type="button" class="lin-btn" data-zoom="1.12">112%</button>' +
                '<button type="button" class="lin-btn" data-star-fs="1">Fullscreen</button>' +
              '</div>' +
            '</div>' +
            '<div class="star-viewport">' +
              '<div class="star-stage">' +
                '<svg class="star-svg"></svg>' +
                '<div class="star-grid"></div>' +
              '</div>' +
            '</div>';

        var pillsEl = shell.querySelector(".star-focus-pills");
        var searchEl = shell.querySelector(".star-search-input");
        var viewportEl = shell.querySelector(".star-viewport");
        var stageEl = shell.querySelector(".star-stage");
        var svgEl = shell.querySelector("svg.star-svg");
        var gridEl = shell.querySelector(".star-grid");

        function dimNeighborsForFact(factName) {
            var set = new Set();
            rels.forEach(function (r) {
                if (r.from_table === factName) set.add(r.to_table);
                else if (r.to_table === factName) set.add(r.from_table);
            });
            return Array.from(set);
        }

        function renderToolbar() {
            var html = "";
            facts.forEach(function (fn) {
                var dimsCnt = dimNeighborsForFact(fn).length;
                var key = "fact:" + fn;
                html += '<button type="button" class="star-pill ' + (state.mode === key ? "active" : "") + '" data-mode="' + escHtml(key) + '" title="Focused Star around ' + escHtml(fn) + '">' +
                    '<span>Star: ' + escHtml(midTrunc(fn, 28)) + '</span>' +
                    '<span style="opacity:0.8;font-size:11px">(' + dimsCnt + ' dim' + (dimsCnt === 1 ? "" : "s") + ')</span>' +
                '</button>';
            });
            html += '<button type="button" class="star-pill ' + (state.mode === "all" ? "active" : "") + '" data-mode="all">All Tables (' + tables.length + ')</button>';
            pillsEl.innerHTML = html;
            searchEl.style.display = (state.mode === "all" && tables.length > 8) ? "" : "none";
        }

        function cardHtml(t, visibleRels) {
            var keyCols = [];
            visibleRels.forEach(function (r) {
                if (r.from_table === t.name && keyCols.indexOf(r.from_column) === -1) keyCols.push(r.from_column);
                if (r.to_table === t.name && keyCols.indexOf(r.to_column) === -1) keyCols.push(r.to_column);
            });
            var roleCls = t.role === "Fact" ? "is-fact" : (t.role === "Dimension" ? "is-dim" : "");
            var badgeCls = t.role === "Fact" ? "badge-fact" : (t.role === "Dimension" ? "badge-dim" : "");
            var keysMarkup = "";
            if (keyCols.length) {
                keysMarkup = '<div class="star-card-keys">' + keyCols.slice(0, 5).map(function (kc) {
                    return '<div class="star-key-item" title="Join column: ' + escHtml(kc) + '"><span class="star-key-dot"></span><span>' + escHtml(midTrunc(kc, 34)) + '</span></div>';
                }).join("") + (keyCols.length > 5 ? '<div style="font-size:10.5px">+' + (keyCols.length - 5) + ' more join key(s)</div>' : '') + '</div>';
            }
            return '<div class="star-card ' + roleCls + '" data-tname="' + escHtml(t.name) + '">' +
                '<div class="star-card-top">' +
                  '<span class="badge ' + badgeCls + '">' + escHtml(t.role) + '</span>' +
                  '<span style="font-size:11px;color:var(--fg-muted);font-family:Consolas,monospace">' + escHtml(t.mode) + '</span>' +
                '</div>' +
                '<div class="star-card-title" title="' + escHtml(t.name) + '">' + escHtml(midTrunc(t.name, 38)) + '</div>' +
                keysMarkup +
                '<div class="star-card-foot">' +
                  '<span>' + t.columns + ' cols' + (t.measures ? ' &bull; <b>' + t.measures + '</b> DAX' : '') + '</span>' +
                  '<a class="star-jump-link" href="#' + escHtml(t.anchor) + '" data-blueprint-jump="' + escHtml(t.anchor) + '">Blueprint &darr;</a>' +
                '</div>' +
            '</div>';
        }

        function drawLines(visibleRels) {
            var stageRect = stageEl.getBoundingClientRect();
            var z = state.zoom || 1.0;
            var w = Math.max(stageEl.scrollWidth, Math.round(stageRect.width / z));
            var h = Math.max(stageEl.scrollHeight, Math.round(stageRect.height / z));
            svgEl.setAttribute("width", String(w));
            svgEl.setAttribute("height", String(h));

            var cardMap = new Map();
            gridEl.querySelectorAll(".star-card[data-tname]").forEach(function (el) {
                cardMap.set(el.getAttribute("data-tname"), el);
            });

            var relatedTables = new Set();
            if (state.activeTable) {
                relatedTables.add(state.activeTable);
                visibleRels.forEach(function (r) {
                    if (r.from_table === state.activeTable) relatedTables.add(r.to_table);
                    if (r.to_table === state.activeTable) relatedTables.add(r.from_table);
                });
            }
            cardMap.forEach(function (el, name) {
                el.classList.toggle("is-active", state.activeTable === name);
                el.classList.toggle("is-muted", Boolean(state.activeTable && !relatedTables.has(name)));
            });

            var parts = [];
            visibleRels.forEach(function (r) {
                var aEl = cardMap.get(r.from_table);
                var bEl = cardMap.get(r.to_table);
                if (!aEl || !bEl) return;
                var a = aEl.getBoundingClientRect();
                var b = bEl.getBoundingClientRect();
                var aCx = (a.left + a.width / 2 - stageRect.left) / z;
                var bCx = (b.left + b.width / 2 - stageRect.left) / z;

                var x1, x2;
                if (aCx <= bCx) {
                    x1 = (a.right - stageRect.left) / z;
                    x2 = (b.left - stageRect.left) / z;
                } else {
                    x1 = (a.left - stageRect.left) / z;
                    x2 = (b.right - stageRect.left) / z;
                }
                var y1 = (a.top + a.height / 2 - stageRect.top) / z;
                var y2 = (b.top + b.height / 2 - stageRect.top) / z;
                var dx = Math.max(32, Math.abs(x2 - x1) * 0.45);
                var c1x = aCx <= bCx ? x1 + dx : x1 - dx;
                var c2x = aCx <= bCx ? x2 - dx : x2 + dx;

                var isHighlighted = !state.activeTable || r.from_table === state.activeTable || r.to_table === state.activeTable;
                var stroke = !isHighlighted ? "rgba(148,163,184,0.22)" : (r.bidirectional ? "#d97706" : "#0b63ce");
                var sw = isHighlighted && state.activeTable ? "2.4" : "1.7";
                var dash = r.active ? "" : ' stroke-dasharray="5,4"';
                parts.push('<path d="M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C ' + c1x.toFixed(1) + ' ' + y1.toFixed(1) + ', ' + c2x.toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + '" fill="none" stroke="' + stroke + '" stroke-width="' + sw + '"' + dash + '/>');

                if (isHighlighted) {
                    var mx = (x1 + x2) / 2;
                    var my = (y1 + y2) / 2;
                    var fCard = r.cardinality.indexOf("many") === 0 ? "*" : "1";
                    var tCard = r.cardinality.slice(-4) === "many" ? "*" : "1";
                    var arrowTxt = r.bidirectional ? "<->" : "->";
                    var lbl = (aCx <= bCx) ? (fCard + " " + arrowTxt + " " + tCard) : (tCard + " " + arrowTxt + " " + fCard);
                    var pillW = r.bidirectional ? 52 : 44;
                    parts.push(
                        '<g transform="translate(' + (mx - pillW / 2).toFixed(1) + ',' + (my - 10).toFixed(1) + ')">' +
                          '<title>' + escHtml(r.from_table + "." + r.from_column + " (" + fCard + ") = " + r.to_table + "." + r.to_column + " (" + tCard + ")") + '</title>' +
                          '<rect width="' + pillW + '" height="20" rx="10" fill="var(--surface)" stroke="' + stroke + '" stroke-width="1.2"/>' +
                          '<text x="' + (pillW / 2) + '" y="13.5" text-anchor="middle" font-size="10.5" font-weight="700" font-family="Consolas,monospace" fill="var(--fg)">' + escHtml(lbl) + '</text>' +
                        '</g>'
                    );
                }
            });
            svgEl.innerHTML = parts.join("");
        }

        function renderDiagram() {
            stageEl.style.transform = state.zoom === 1 ? "" : ("scale(" + state.zoom + ")");
            var visibleRels = rels.slice();
            gridEl.classList.remove("two-col", "one-col");

            if (state.mode.indexOf("fact:") === 0) {
                var fName = state.mode.slice(5);
                var factTbl = tblByName.get(fName);
                if (!factTbl) { state.mode = "all"; return renderDiagram(); }
                var neighborNames = dimNeighborsForFact(fName);
                visibleRels = rels.filter(function (r) { return r.from_table === fName || r.to_table === fName; });

                var neighborTbls = neighborNames.map(function (n) { return tblByName.get(n); }).filter(Boolean);
                if (!neighborTbls.length) {
                    gridEl.classList.add("one-col");
                    gridEl.innerHTML = '<div class="star-col"><div class="star-col-label">Fact Table</div>' + cardHtml(factTbl, visibleRels) + '</div>';
                } else if (neighborTbls.length === 1) {
                    gridEl.classList.add("two-col");
                    gridEl.innerHTML =
                        '<div class="star-col"><div class="star-col-label">Linked Dimension (1)</div>' + cardHtml(neighborTbls[0], visibleRels) + '</div>' +
                        '<div class="star-col"><div class="star-col-label">Central Fact Table</div>' + cardHtml(factTbl, visibleRels) + '</div>';
                } else {
                    var half = Math.ceil(neighborTbls.length / 2);
                    var leftDims = neighborTbls.slice(0, half);
                    var rightDims = neighborTbls.slice(half);
                    gridEl.innerHTML =
                        '<div class="star-col"><div class="star-col-label">Dimensions (' + leftDims.length + ')</div>' + leftDims.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>' +
                        '<div class="star-col"><div class="star-col-label">Central Fact Table</div>' + cardHtml(factTbl, visibleRels) + '</div>' +
                        '<div class="star-col"><div class="star-col-label">Dimensions (' + rightDims.length + ')</div>' + rightDims.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>';
                }
            } else {
                var q = state.search.toLowerCase().trim();
                var filtered = tables.filter(function (t) {
                    return !q || t.name.toLowerCase().indexOf(q) !== -1 || t.role.toLowerCase().indexOf(q) !== -1;
                });
                var fSet = new Set(filtered.map(function (t) { return t.name; }));
                visibleRels = rels.filter(function (r) { return fSet.has(r.from_table) && fSet.has(r.to_table); });

                var factCol = filtered.filter(function (t) { return t.role === "Fact"; });
                var dimCol = filtered.filter(function (t) { return t.role === "Dimension"; });
                var otherCol = filtered.filter(function (t) { return t.role !== "Fact" && t.role !== "Dimension"; });

                if (!factCol.length && !dimCol.length) {
                    gridEl.innerHTML = '<div class="star-col"><div class="star-col-label">Tables (' + otherCol.length + ')</div>' + otherCol.map(function (t) { return cardHtml(t, visibleRels); }).join("") + '</div>';
                    gridEl.classList.add("one-col");
                } else {
                    var halfD = Math.ceil(dimCol.length / 2);
                    var leftD = dimCol.slice(0, halfD);
                    var rightD = dimCol.slice(halfD).concat(otherCol);
                    if (!rightD.length) {
                        gridEl.classList.add("two-col");
                        gridEl.innerHTML =
                            '<div class="star-col"><div class="star-col-label">Dimensions (' + leftD.length + ')</div>' + leftD.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>' +
                            '<div class="star-col"><div class="star-col-label">Fact Tables (' + factCol.length + ')</div>' + factCol.map(function (f) { return cardHtml(f, visibleRels); }).join("") + '</div>';
                    } else {
                        gridEl.innerHTML =
                            '<div class="star-col"><div class="star-col-label">Dimensions (' + leftD.length + ')</div>' + leftD.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>' +
                            '<div class="star-col"><div class="star-col-label">Fact Tables (' + factCol.length + ')</div>' + factCol.map(function (f) { return cardHtml(f, visibleRels); }).join("") + '</div>' +
                            '<div class="star-col"><div class="star-col-label">Dimensions &amp; KPI Tables (' + rightD.length + ')</div>' + rightD.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>';
                    }
                }
            }

            window.requestAnimationFrame(function () { drawLines(visibleRels); });
            shell._currentVisibleRels = visibleRels;
        }

        pillsEl.addEventListener("click", function (e) {
            var b = e.target.closest("button[data-mode]");
            if (!b) return;
            state.mode = b.getAttribute("data-mode");
            state.activeTable = null;
            renderToolbar();
            renderDiagram();
        });

        searchEl.addEventListener("input", function () {
            state.search = searchEl.value || "";
            renderDiagram();
        });

        shell.querySelector(".star-actions").addEventListener("click", function (e) {
            var zb = e.target.closest("button[data-zoom]");
            if (zb) {
                state.zoom = parseFloat(zb.getAttribute("data-zoom") || "1");
                shell.querySelectorAll("button[data-zoom]").forEach(function (btn) { btn.classList.toggle("active", btn === zb); });
                renderDiagram();
                return;
            }
            var fs = e.target.closest("button[data-star-fs]");
            if (fs) {
                var isFs = shell.classList.toggle("is-fullscreen");
                document.body.classList.toggle("star-fullscreen-lock", isFs);
                fs.textContent = isFs ? "Exit Fullscreen" : "Fullscreen";
                setTimeout(function () { drawLines(shell._currentVisibleRels || []); }, 40);
            }
        });

        gridEl.addEventListener("click", function (e) {
            var jump = e.target.closest("[data-blueprint-jump]");
            if (jump) {
                var targetId = jump.getAttribute("data-blueprint-jump");
                var det = document.getElementById(targetId);
                if (det && det.tagName === "DETAILS") det.open = true;
                if (shell.classList.contains("is-fullscreen")) {
                    shell.classList.remove("is-fullscreen");
                    document.body.classList.remove("star-fullscreen-lock");
                }
                return;
            }
            var card = e.target.closest(".star-card[data-tname]");
            if (!card) return;
            var nm = card.getAttribute("data-tname");
            state.activeTable = (state.activeTable === nm) ? null : nm;
            drawLines(shell._currentVisibleRels || []);
        });

        viewportEl.addEventListener("scroll", function () { drawLines(shell._currentVisibleRels || []); });
        window.addEventListener("resize", function () { drawLines(shell._currentVisibleRels || []); });

        renderToolbar();
        renderDiagram();
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".star-shell[data-star-id]").forEach(initStarApp);
    });
})();
