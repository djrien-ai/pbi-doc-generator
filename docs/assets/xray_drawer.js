
(function () {
    function escHtml(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function midTrunc(s, maxLen) {
        s = String(s || "");
        if (s.length <= maxLen) return s;
        var keep = Math.max(8, maxLen - 3);
        var head = Math.floor(keep * 0.56);
        return s.slice(0, head) + "..." + s.slice(-(keep - head));
    }

    var registry = {};
    var reportOrder = [];
    var activeItemId = null;
    var activePageIdx = 0;
    var activeVisIdx = 0;
    var activeBrokenCursor = -1;
    var pulseBrokenOnce = false;
    var showHiddenVisuals = false;
    var pageFilter = "";
    var backdropEl = null;
    var drawerEl = null;

    function visualTag(vtype) {
        var t = String(vtype || "").toLowerCase();
        if (t === "group") return "GRP";
        if (t.indexOf("slicer") !== -1) return "SLC";
        if (t.indexOf("card") !== -1) return "CARD";
        if (t.indexOf("kpi") !== -1) return "KPI";
        if (t.indexOf("matrix") !== -1 || t.indexOf("pivot") !== -1) return "MTX";
        if (t.indexOf("table") !== -1) return "TBL";
        if (t.indexOf("combo") !== -1) return "CMB";
        if (t.indexOf("line") !== -1 || t.indexOf("area") !== -1) return "LINE";
        if (t.indexOf("bar") !== -1 || t.indexOf("column") !== -1 || t.indexOf("waterfall") !== -1) return "BAR";
        if (t.indexOf("pie") !== -1 || t.indexOf("donut") !== -1) return "PIE";
        if (t.indexOf("map") !== -1) return "MAP";
        if (t.indexOf("gauge") !== -1) return "GAU";
        if (t.indexOf("text") !== -1) return "TXT";
        return "VIS";
    }

    function visualGlyphSvg(vtype, gx, gy, hasBroken) {
        var t = String(vtype || "").toLowerCase();
        var paths = "";
        if (t === "group") {
            paths = '<rect x="1.5" y="2" width="11" height="10" rx="1.5" stroke-dasharray="2.5,2"/>';
        } else if (t.indexOf("slicer") !== -1 || t.indexOf("filter") !== -1) {
            paths = '<path d="M2 2.5h10L8 7.2v3.8L6 12V7.2Z"/>';
        } else if (t.indexOf("card") !== -1 || t.indexOf("kpi") !== -1) {
            paths = '<rect x="1.5" y="2.5" width="11" height="9" rx="2"/><path d="M4.2 6.5h5.6M4.2 9h3.4"/>';
        } else if (t.indexOf("matrix") !== -1 || t.indexOf("pivot") !== -1 || t.indexOf("table") !== -1) {
            paths = '<rect x="1.5" y="2" width="11" height="10" rx="1.5"/><path d="M1.5 5.4h11M1.5 8.6h11M5.3 2v10"/>';
        } else if (t.indexOf("combo") !== -1) {
            paths = '<path d="M2.5 12V7.5M7 12V5M11.5 12V8.5"/><path d="M2 6.5L7 3.5L12 5.5"/>';
        } else if (t.indexOf("line") !== -1 || t.indexOf("area") !== -1) {
            paths = '<path d="M1.5 11L5 6.8L8.4 8.6L12.5 3.2"/><path d="M1.5 12.2h11"/>';
        } else if (t.indexOf("bar") !== -1) {
            paths = '<path d="M2 3.2h8.5M2 7h10.5M2 10.8h6"/>';
        } else if (t.indexOf("column") !== -1 || t.indexOf("waterfall") !== -1 || t.indexOf("ribbon") !== -1) {
            paths = '<rect x="2" y="6.5" width="2.4" height="5.5" rx="0.5"/><rect x="5.8" y="3" width="2.4" height="9" rx="0.5"/><rect x="9.6" y="5" width="2.4" height="7" rx="0.5"/>';
        } else if (t.indexOf("pie") !== -1 || t.indexOf("donut") !== -1) {
            paths = '<circle cx="7" cy="7" r="5"/><path d="M7 2v5h5"/>';
        } else if (t.indexOf("map") !== -1) {
            paths = '<path d="M7 12.5C7 12.5 11 8.8 11 5.7A4 4 0 1 0 3 5.7C3 8.8 7 12.5 7 12.5Z"/><circle cx="7" cy="5.7" r="1.3"/>';
        } else if (t.indexOf("gauge") !== -1) {
            paths = '<path d="M2 10.5A5 5 0 0 1 12 10.5"/><path d="M7 10.5L9.8 6.2"/>';
        } else if (t.indexOf("text") !== -1 || t.indexOf("button") !== -1) {
            paths = '<path d="M3 3.2h8M7 3.2v8.2"/>';
        } else {
            paths = '<rect x="2" y="2.5" width="10" height="9" rx="1.8"/><circle cx="5.2" cy="5.8" r="1"/><path d="M3.5 10l2.8-2.4 2.2 1.8 2-1.4"/>';
        }
        var pillFill = hasBroken ? "var(--bad-bg)" : "var(--accent-soft)";
        var pillStroke = hasBroken ? "var(--bad)" : "var(--accent)";
        return '<g class="xray-vis-glyph" transform="translate(' + gx + ',' + gy + ')">' +
            '<rect x="0" y="0" width="24" height="24" rx="5" fill="' + pillFill + '" stroke="' + pillStroke + '" stroke-width="1.2" opacity="0.92"/>' +
            '<g transform="translate(2.2,2.2) scale(1.4)" stroke="' + pillStroke + '" stroke-width="1.65" fill="none" stroke-linecap="round" stroke-linejoin="round">' + paths + '</g>' +
            '</g>';
    }

    function visualSchematicSvg(vtype, x, y, w, h, hasBroken) {
        var t = String(vtype || "").toLowerCase();
        if (t === "group" || w < 120 || h < 88) return "";
        var sx = x + 16;
        var sy = y + 66;
        var sw = Math.max(40, w - 32);
        var sh = Math.max(20, h - 78);
        if (sh < 22) return "";
        var col = hasBroken ? "var(--bad)" : "var(--accent)";
        var out = '<g class="xray-vis-schematic" opacity="0.28" pointer-events="none">';
        if (t.indexOf("column") !== -1 || t.indexOf("waterfall") !== -1 || t.indexOf("ribbon") !== -1 || t.indexOf("combo") !== -1) {
            var nBars = Math.min(7, Math.max(4, Math.floor(sw / 52)));
            var gap = 10;
            var bw = Math.max(10, Math.min(44, (sw - gap * (nBars - 1)) / nBars));
            var totalW = nBars * bw + (nBars - 1) * gap;
            var startX = sx + Math.max(0, (sw - totalW) / 2);
            var heights = [0.52, 0.86, 0.68, 0.95, 0.61, 0.78, 0.46];
            for (var i = 0; i < nBars; i++) {
                var bh = Math.max(8, sh * heights[i % heights.length]);
                out += '<rect x="' + (startX + i * (bw + gap)).toFixed(1) + '" y="' + (sy + sh - bh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="3" fill="' + col + '"/>';
            }
            out += '<line x1="' + sx + '" y1="' + (sy + sh) + '" x2="' + (sx + sw) + '" y2="' + (sy + sh) + '" stroke="' + col + '" stroke-width="2"/>';
        } else if (t.indexOf("bar") !== -1) {
            var nRows = Math.min(5, Math.max(3, Math.floor(sh / 26)));
            var rgap = 8;
            var rh = Math.max(8, Math.min(22, (sh - rgap * (nRows - 1)) / nRows));
            var widths = [0.88, 0.64, 0.94, 0.48, 0.73];
            for (var r = 0; r < nRows; r++) {
                out += '<rect x="' + sx + '" y="' + (sy + r * (rh + rgap)).toFixed(1) + '" width="' + (sw * widths[r % widths.length]).toFixed(1) + '" height="' + rh.toFixed(1) + '" rx="3" fill="' + col + '"/>';
            }
        } else if (t.indexOf("line") !== -1 || t.indexOf("area") !== -1) {
            var pts = [
                [sx, sy + sh * 0.78],
                [sx + sw * 0.25, sy + sh * 0.46],
                [sx + sw * 0.5, sy + sh * 0.60],
                [sx + sw * 0.75, sy + sh * 0.24],
                [sx + sw, sy + sh * 0.14]
            ];
            var poly = pts.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
            out += '<polyline points="' + poly + '" fill="none" stroke="' + col + '" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>';
            pts.forEach(function (p) {
                out += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="4" fill="' + col + '"/>';
            });
            out += '<line x1="' + sx + '" y1="' + (sy + sh) + '" x2="' + (sx + sw) + '" y2="' + (sy + sh) + '" stroke="' + col + '" stroke-width="1.8"/>';
        } else if (t.indexOf("pie") !== -1 || t.indexOf("donut") !== -1) {
            var rad = Math.max(14, Math.min(sw, sh) * 0.42);
            var cx = sx + sw / 2;
            var cy = sy + sh / 2;
            out += '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + rad.toFixed(1) + '" fill="none" stroke="' + col + '" stroke-width="' + Math.max(6, rad * 0.36).toFixed(1) + '"/>';
            out += '<line x1="' + cx.toFixed(1) + '" y1="' + (cy - rad).toFixed(1) + '" x2="' + cx.toFixed(1) + '" y2="' + cy.toFixed(1) + '" stroke="var(--surface)" stroke-width="3"/>';
        } else if (t.indexOf("matrix") !== -1 || t.indexOf("pivot") !== -1 || t.indexOf("table") !== -1) {
            var gh = Math.min(sh, 150);
            out += '<rect x="' + sx + '" y="' + sy + '" width="' + sw + '" height="' + gh + '" rx="4" fill="none" stroke="' + col + '" stroke-width="1.8"/>';
            out += '<rect x="' + sx + '" y="' + sy + '" width="' + sw + '" height="' + Math.min(22, gh * 0.26) + '" rx="3" fill="' + col + '"/>';
            for (var gr = 1; gr <= 3; gr++) {
                var gyLine = sy + (gh * gr) / 4;
                out += '<line x1="' + sx + '" y1="' + gyLine.toFixed(1) + '" x2="' + (sx + sw) + '" y2="' + gyLine.toFixed(1) + '" stroke="' + col + '" stroke-width="1.3"/>';
            }
            out += '<line x1="' + (sx + sw * 0.36).toFixed(1) + '" y1="' + sy + '" x2="' + (sx + sw * 0.36).toFixed(1) + '" y2="' + (sy + gh) + '" stroke="' + col + '" stroke-width="1.3"/>';
            out += '<line x1="' + (sx + sw * 0.68).toFixed(1) + '" y1="' + sy + '" x2="' + (sx + sw * 0.68).toFixed(1) + '" y2="' + (sy + gh) + '" stroke="' + col + '" stroke-width="1.3"/>';
        } else if (t.indexOf("card") !== -1 || t.indexOf("kpi") !== -1) {
            var kh = Math.min(20, sh * 0.42);
            out += '<rect x="' + sx + '" y="' + (sy + 4) + '" width="' + Math.min(130, sw * 0.55).toFixed(1) + '" height="' + kh.toFixed(1) + '" rx="4" fill="' + col + '"/>';
            if (sh >= 38) {
                out += '<rect x="' + sx + '" y="' + (sy + kh + 10).toFixed(1) + '" width="' + Math.min(84, sw * 0.35).toFixed(1) + '" height="8" rx="3" fill="' + col + '" opacity="0.65"/>';
            }
        } else if (t.indexOf("slicer") !== -1 || t.indexOf("filter") !== -1) {
            var dh = Math.min(26, sh * 0.65);
            out += '<rect x="' + sx + '" y="' + sy + '" width="' + sw + '" height="' + dh.toFixed(1) + '" rx="4" fill="none" stroke="' + col + '" stroke-width="1.8"/>';
            var ax = sx + sw - 16;
            var ay = sy + dh / 2 - 2;
            out += '<path d="M' + (ax - 5) + ' ' + ay + 'L' + ax + ' ' + (ay + 5) + 'L' + (ax + 5) + ' ' + ay + '" fill="none" stroke="' + col + '" stroke-width="2" stroke-linecap="round"/>';
        }
        out += '</g>';
        return out;
    }

    function getBrokenTargets(item) {
        if (!item || item.kind !== "report") return [];
        var out = [];
        (item.pages || []).forEach(function (pg, pIdx) {
            (pg.visuals || []).forEach(function (v) {
                var brCnt = (v.broken_refs || []).length;
                if (!brCnt && v.fields) {
                    brCnt = v.fields.filter(function (f) { return f.broken; }).length;
                }
                if (brCnt > 0) {
                    out.push({
                        pageIdx: pIdx,
                        visRef: v,
                        visId: v.id,
                        hidden: !!v.hidden,
                        fieldCount: brCnt,
                        pageName: pg.name || ("Page " + (pIdx + 1)),
                        visTitle: v.title || v.type_label || "Visual"
                    });
                }
            });
        });
        return out;
    }

    function jumpToBrokenIndex(idx) {
        var item = registry[activeItemId];
        var targets = getBrokenTargets(item);
        if (!targets.length) return;
        var normIdx = ((idx % targets.length) + targets.length) % targets.length;
        var t = targets[normIdx];
        activeBrokenCursor = normIdx;
        if (t.hidden) showHiddenVisuals = true;
        activePageIdx = t.pageIdx;
        var pg = (item.pages || [])[activePageIdx];
        var visList = getVisibleVisuals(pg);
        var foundVisIdx = visList.indexOf(t.visRef);
        if (foundVisIdx === -1 && t.visId) {
            foundVisIdx = visList.findIndex(function (cand) { return cand.id === t.visId; });
        }
        activeVisIdx = foundVisIdx >= 0 ? foundVisIdx : 0;
        pulseBrokenOnce = true;
        renderDrawerContent();
        setTimeout(function () {
            var activePgBtn = drawerEl && drawerEl.querySelector(".xray-page-btn.active");
            if (activePgBtn && activePgBtn.scrollIntoView) activePgBtn.scrollIntoView({ block: "nearest" });
            var brokenFld = drawerEl && drawerEl.querySelector(".xray-inspector-pane .xray-field-item.is-broken");
            if (brokenFld && brokenFld.scrollIntoView) brokenFld.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }, 35);
    }

    function ensureDrawerDom() {
        if (drawerEl) return;
        var dataTag = document.getElementById("xrayRegistryData");
        if (dataTag) {
            try {
                var parsed = JSON.parse(dataTag.textContent || "{}");
                registry = parsed.items || {};
                reportOrder = parsed.reportOrder || [];
            } catch (e) { registry = {}; }
        }
        backdropEl = document.createElement("div");
        backdropEl.className = "xray-backdrop";
        drawerEl = document.createElement("aside");
        drawerEl.className = "xray-drawer";
        drawerEl.setAttribute("role", "dialog");
        drawerEl.setAttribute("aria-modal", "true");
        document.body.appendChild(backdropEl);
        document.body.appendChild(drawerEl);

        backdropEl.addEventListener("click", closeDrawer);
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && drawerEl.classList.contains("is-open")) closeDrawer();
        });

        drawerEl.addEventListener("click", function (e) {
            if (e.target.closest("[data-xray-close]")) { closeDrawer(); return; }
            var brGo = e.target.closest("[data-xray-broken-go]");
            if (brGo) {
                var targetK = parseInt(brGo.getAttribute("data-xray-broken-go"), 10) || 0;
                jumpToBrokenIndex(targetK);
                return;
            }
            var brStep = e.target.closest("[data-xray-broken-step]");
            if (brStep) {
                var stepDir = parseInt(brStep.getAttribute("data-xray-broken-step"), 10) || 1;
                var nextK = activeBrokenCursor < 0 ? 0 : activeBrokenCursor + stepDir;
                jumpToBrokenIndex(nextK);
                return;
            }
            var hidBtn = e.target.closest("[data-xray-toggle-hidden]");
            if (hidBtn) {
                showHiddenVisuals = !showHiddenVisuals;
                activeVisIdx = 0;
                renderDrawerContent();
                return;
            }
            var navBtn = e.target.closest("[data-xray-step]");
            if (navBtn && reportOrder.length > 1) {
                var dir = parseInt(navBtn.getAttribute("data-xray-step"), 10);
                var idx = reportOrder.indexOf(activeItemId);
                if (idx !== -1) {
                    var nxt = (idx + dir + reportOrder.length) % reportOrder.length;
                    openDrawer(reportOrder[nxt]);
                }
                return;
            }
            var pgBtn = e.target.closest("[data-xray-page]");
            if (pgBtn) {
                activePageIdx = parseInt(pgBtn.getAttribute("data-xray-page"), 10) || 0;
                var curItem = registry[activeItemId];
                activeVisIdx = defaultVisIndex(curItem && curItem.pages ? curItem.pages[activePageIdx] : null);
                renderDrawerContent();
                return;
            }
            var visGrp = e.target.closest("[data-xray-vis]");
            if (visGrp) {
                activeVisIdx = parseInt(visGrp.getAttribute("data-xray-vis"), 10) || 0;
                renderDrawerContent();
                return;
            }
            var traceBtn = e.target.closest("[data-trace-e2e]");
            if (traceBtn) {
                var e2eId = traceBtn.getAttribute("data-trace-e2e");
                closeDrawer();
                if (window.PbiFocusLineage && e2eId) {
                    window.PbiFocusLineage(e2eId);
                }
                return;
            }
            var mJump = e.target.closest("[data-xray-jump-anchor]");
            if (mJump) {
                var href = mJump.getAttribute("data-xray-jump-anchor");
                closeDrawer();
                if (href && href.charAt(0) === "#") {
                    var cardsBtn = document.querySelector('[data-dax-view="cards"]');
                    if (cardsBtn && !cardsBtn.classList.contains("active")) cardsBtn.click();
                    var target = document.getElementById(href.slice(1));
                    if (target) {
                        var parentDet = target.closest("details.dax-folder-details");
                        if (parentDet) parentDet.open = true;
                        var hostDet = target.closest("details.dax-table-group");
                        if (hostDet) hostDet.open = true;
                        if (target.tagName === "DETAILS") target.open = true;
                        target.scrollIntoView({ behavior: "smooth", block: "center" });
                    }
                } else if (href) {
                    window.location.href = href;
                }
            }
        });

        drawerEl.addEventListener("input", function (e) {
            if (e.target.matches("[data-xray-page-search]")) {
                pageFilter = e.target.value || "";
                renderPagesListOnly();
            }
        });
    }

    function closeDrawer() {
        if (!drawerEl) return;
        backdropEl.classList.remove("is-open");
        drawerEl.classList.remove("is-open");
        document.body.classList.remove("xray-open-lock");
    }

    function defaultVisIndex(pg) {
        var list = getVisibleVisuals(pg);
        var brkIdx = list.findIndex(function (v) { return v.type !== "group" && ((v.broken_refs || []).length > 0 || (v.fields && v.fields.some(function (f) { return f.broken; }))); });
        if (brkIdx >= 0) return brkIdx;
        var idx = list.findIndex(function (v) { return v.type !== "group" && !v.decorative && v.fields && v.fields.length > 0; });
        if (idx >= 0) return idx;
        var nonGrp = list.findIndex(function (v) { return v.type !== "group"; });
        return nonGrp >= 0 ? nonGrp : 0;
    }

    function openDrawer(itemId, autoJumpBroken) {
        ensureDrawerDom();
        if (!registry[itemId]) return;
        activeItemId = itemId;
        activePageIdx = 0;
        var firstPg = (registry[itemId].pages || [])[0] || null;
        activeVisIdx = defaultVisIndex(firstPg);
        activeBrokenCursor = -1;
        pulseBrokenOnce = false;
        pageFilter = "";
        renderDrawerContent();
        backdropEl.classList.add("is-open");
        drawerEl.classList.add("is-open");
        document.body.classList.add("xray-open-lock");
        if (autoJumpBroken) {
            jumpToBrokenIndex(0);
        }
    }

    function getVisibleVisuals(pg) {
        var all = (pg && pg.visuals) ? pg.visuals.slice() : [];
        all.sort(function (a, b) {
            var ga = a.type === "group" ? 0 : 1;
            var gb = b.type === "group" ? 0 : 1;
            if (ga !== gb) return ga - gb;
            return (a.z || 0) - (b.z || 0);
        });
        if (showHiddenVisuals) return all;
        return all.filter(function (v) { return !v.hidden; });
    }

    function renderPagesListOnly() {
        var item = registry[activeItemId];
        if (!item || item.kind !== "report") return;
        var listWrap = drawerEl.querySelector(".xray-pages-list");
        if (!listWrap) return;
        var pages = item.pages || [];
        var q = pageFilter.toLowerCase().trim();
        listWrap.innerHTML = pages.map(function (pg, i) {
            if (q && pg.name.toLowerCase().indexOf(q) === -1) return "";
            var brokenCnt = (pg.visuals || []).reduce(function (acc, v) { return acc + ((v.broken_refs || []).length ? 1 : 0); }, 0);
            var cleanPgName = /^\d+[\.\)\s-]/.test(pg.name || "") ? pg.name : ((i + 1) + ". " + pg.name);
            return '<button type="button" class="xray-page-btn ' + (i === activePageIdx ? "active" : "") + '" data-xray-page="' + i + '">' +
                '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px">' +
                  '<span title="' + escHtml(pg.name) + '" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(cleanPgName) + '</span>' +
                  (brokenCnt ? '<span class="badge badge-bad" style="font-size:10px;padding:1px 5px;flex-shrink:0">' + brokenCnt + '!</span>' : '') +
                '</div>' +
                '<span style="font-size:10.5px;color:var(--fg-muted)">' + (pg.visuals || []).length + ' visuals' + (pg.hidden ? ' &bull; Hidden' : '') + '</span>' +
            '</button>';
        }).join("");
    }

    function renderWireframeSvg(pg, visuals) {
        var pw = Math.max(320, pg.width || 1280);
        var ph = Math.max(200, pg.height || 720);
        var defs = [];
        var shapes = [];

        visuals.forEach(function (v, idx) {
            var x = Math.max(0, Math.min(pw - 24, v.x || 0));
            var y = Math.max(0, Math.min(ph - 20, v.y || 0));
            var w = Math.max(36, Math.min(pw - x, v.width || 160));
            var h = Math.max(26, Math.min(ph - y, v.height || 100));
            var clipId = "xrclip-" + activePageIdx + "-" + idx;
            defs.push('<clipPath id="' + clipId + '"><rect x="' + (x + 6) + '" y="' + (y + 4) + '" width="' + Math.max(10, w - 12) + '" height="' + Math.max(10, h - 8) + '"/></clipPath>');

            var isGroup = v.type === "group";
            var hasBroken = (v.broken_refs || []).length > 0 || !!(v.fields && v.fields.some(function (f) { return f.broken; }));
            var fill = hasBroken ? "var(--bad-bg)" : (isGroup ? "rgba(148,163,184,0.07)" : (v.decorative ? "var(--surface-alt)" : "var(--surface)"));
            var stroke = hasBroken ? "var(--bad)" : (idx === activeVisIdx ? "var(--accent)" : "var(--border)");
            var sw = (idx === activeVisIdx || hasBroken) ? "2.5" : "1.4";
            var dashAttr = (isGroup || v.hidden) ? ' stroke-dasharray="6,4"' : '';
            var opAttr = v.hidden ? ' opacity="0.68"' : '';
            var selCls = idx === activeVisIdx ? " is-selected" : "";
            if (idx === activeVisIdx && hasBroken && pulseBrokenOnce) {
                selCls += " is-broken-pulse";
            }

            if (isGroup) {
                shapes.push(
                    '<g class="xray-vis-group' + selCls + '" data-xray-vis="' + idx + '" data-vtype="group"' + opAttr + '>' +
                      '<title>' + escHtml("Visual Group: " + (v.title || "Group")) + '</title>' +
                      '<rect class="vis-box" x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="7" fill="rgba(148,163,184,0.04)" stroke="' + stroke + '" stroke-width="1.2" stroke-dasharray="6,4"/>' +
                    '</g>'
                );
                return;
            }

            var showLeadGlyph = (w >= 72 && h >= 32);
            var textX = showLeadGlyph ? (x + 38) : (x + 10);
            var rightPad = hasBroken ? 36 : 12;
            var maxChars = Math.max(5, Math.floor((w - (textX - x) - rightPad) / 6.9));
            var hdrLbl = midTrunc(v.title || v.type_label || "Visual", maxChars);
            var subLbl = midTrunc(v.type_label + (v.fields && v.fields.length ? " (" + v.fields.length + ")" : ""), maxChars + 3);
            var glyphMarkup = showLeadGlyph ? visualGlyphSvg(v.type, x + 8, y + 7, hasBroken) : "";
            var brokenBadgeSvg = (hasBroken && w >= 96 && h >= 32)
                ? ('<g transform="translate(' + (x + w - 30) + ',' + (y + 8) + ')" stroke="var(--bad)" stroke-width="2" fill="var(--bad-bg)" stroke-linecap="round" stroke-linejoin="round">' +
                   '<path d="M11 2.5L20 18.5H2Z"/><path d="M11 8.5v4.5M11 15.8h0.02"/></g>')
                : "";
            var schematicMarkup = visualSchematicSvg(v.type, x, y, w, h, hasBroken);

            var textLines = '<text x="' + textX + '" y="' + (y + 23) + '" font-size="13" font-weight="700" fill="var(--fg)">' + escHtml(hdrLbl) + '</text>';
            if (h >= 50) {
                textLines += '<text x="' + (x + 10) + '" y="' + (y + 44) + '" font-size="11.5" fill="var(--fg-muted)">' + escHtml(subLbl) + '</text>';
            }
            if (h >= 76 && v.fields && v.fields.length) {
                var f0 = v.fields[0];
                textLines += '<text x="' + (x + 10) + '" y="' + (y + 61) + '" font-size="11" font-family="Consolas,monospace" fill="var(--accent)">' + escHtml(midTrunc(f0.display || f0.property, maxChars + 4)) + '</text>';
            }

            shapes.push(
                '<g class="xray-vis-group' + selCls + '" data-xray-vis="' + idx + '" data-vtype="' + escHtml(v.type || "") + '"' + opAttr + '>' +
                  '<title>' + escHtml((v.title || v.type_label) + (v.hidden ? " [Hidden]" : "") + (hasBroken ? " [Broken Field Binding!]" : "") + " - Click to inspect bindings") + '</title>' +
                  '<rect class="vis-box" x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="6" fill="' + fill + '" stroke="' + stroke + '" stroke-width="' + sw + '"' + dashAttr + '/>' +
                  schematicMarkup +
                  glyphMarkup +
                  brokenBadgeSvg +
                  '<g clip-path="url(#' + clipId + ')">' + textLines + '</g>' +
                '</g>'
            );
        });
        pulseBrokenOnce = false;

        return '<svg viewBox="0 0 ' + pw + ' ' + ph + '" xmlns="http://www.w3.org/2000/svg">' +
            '<defs>' + defs.join("") + '</defs>' +
            '<rect width="' + pw + '" height="' + ph + '" fill="var(--surface-alt)" opacity="0.45"/>' +
            shapes.join("") +
        '</svg>';
    }

    function renderDrawerContent() {
        var item = registry[activeItemId];
        if (!item) return;

        if (item.kind === "dataflow") {
            var genLbl = String(item.generation || "Gen1").replace(/^Gen/i, "");
            var genBadgeTxt = genLbl === "2" ? "Fabric Dataflow Gen2" : "Power BI Dataflow Gen1";
            var entHtml = (item.entities || []).length
                ? (item.entities || []).map(function (ent) {
                    var rolePill = ent.role ? '<span class="badge">' + escHtml(ent.role) + '</span>' : '';
                    return '<div class="card" style="padding:14px 16px">' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">' +
                          '<b>Query / Entity: <code>' + escHtml(ent.name) + '</code></b>' +
                          '<div class="model-meta">' + rolePill + '<span class="badge badge-dim">' + ent.columns_count + ' columns</span><span class="badge">' + ent.pq_steps + ' PQ steps</span></div>' +
                        '</div>' +
                        (ent.description ? '<div style="font-size:12px;color:var(--fg-muted);margin-top:4px">' + escHtml(ent.description) + '</div>' : '') +
                        (ent.pq_block_html || ent.pipeline_html || '') +
                        (!ent.pq_block_html ? (ent.m_html || '') : '') +
                    '</div>';
                }).join("")
                : '<div class="card"><p style="margin:0;color:var(--fg-muted)">Entity-level M definition was not returned by the workspace API (metadata-only Dataflow entry).</p></div>';

            drawerEl.innerHTML =
                '<div class="xray-header">' +
                  '<div>' +
                    '<div class="model-meta"><span class="badge badge-dim">' + escHtml(genBadgeTxt) + '</span><span class="badge">Workspace: ' + escHtml(item.workspace) + '</span></div>' +
                    '<h3>' + escHtml(item.name) + '</h3>' +
                    (item.description ? '<div style="font-size:12.5px;color:var(--fg-muted)">' + escHtml(item.description) + '</div>' : '') +
                  '</div>' +
                  '<div class="xray-header-controls">' +
                    '<button type="button" class="lin-btn" data-xray-close="1">Close (Esc)</button>' +
                  '</div>' +
                '</div>' +
                '<div class="xray-body">' + entHtml + '</div>';
            return;
        }

        // Report X-Ray Drawer
        var posIdx = reportOrder.indexOf(activeItemId);
        var navHtml = reportOrder.length > 1 && posIdx !== -1
            ? '<button type="button" class="lin-btn" data-xray-step="-1">&larr; Prev</button>' +
              '<span style="font-size:11.5px;color:var(--fg-muted);padding:0 4px">' + (posIdx + 1) + ' / ' + reportOrder.length + '</span>' +
              '<button type="button" class="lin-btn" data-xray-step="1">Next &rarr;</button>'
            : '';

        var pages = item.pages || [];
        var bodyInner = "";

        if (!pages.length) {
            bodyInner = '<div class="card"><p style="margin:0;color:var(--fg-muted)">Visual page layout is not stored yet for this report. Re-scan with Contributor+ workspace permissions or import the <code>.pbix</code> / <code>.pbip</code> file locally to inspect visual bindings.</p></div>';
        } else {
            var pg = pages[Math.min(activePageIdx, pages.length - 1)];
            var totalHidden = (pg.visuals || []).filter(function (v) { return v.hidden; }).length;
            var visuals = getVisibleVisuals(pg);
            var selVis = visuals[Math.min(activeVisIdx, Math.max(0, visuals.length - 1))] || null;

            var hidToggleHtml = totalHidden > 0
                ? '<button type="button" class="lin-btn ' + (showHiddenVisuals ? "active" : "") + '" data-xray-toggle-hidden="1">' +
                  (showHiddenVisuals ? "Hide" : "Show") + ' hidden (' + totalHidden + ')</button>'
                : '';

            var inspHtml = "";
            if (selVis) {
                var flds = selVis.fields || [];
                var fldsHtml = flds.length
                    ? flds.map(function (f) {
                        var statusPill = f.broken
                            ? '<span class="badge badge-bad">Missing in Model</span>'
                            : (f.is_report_measure ? '<span class="badge badge-warn">Report-Level DAX</span>' : '');
                        var btnRow = [];
                        if (!f.broken && f.anchor_href) {
                            btnRow.push('<button type="button" class="lin-btn" style="padding:2px 7px;font-size:10.5px" data-xray-jump-anchor="' + escHtml(f.anchor_href) + '">View in Model &rarr;</button>');
                        }
                        if (!f.broken && f.e2e_id) {
                            btnRow.push('<button type="button" class="lin-btn" style="padding:2px 7px;font-size:10.5px;border-color:var(--accent);color:var(--accent)" data-trace-e2e="' + escHtml(f.e2e_id) + '">Trace to SQL &rarr;</button>');
                        }
                        var btnsMarkup = btnRow.length ? '<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:5px">' + btnRow.join("") + '</div>' : '';
                        return '<div class="xray-field-item ' + (f.broken ? "is-broken" : "") + '">' +
                            '<div style="display:flex;justify-content:space-between;align-items:center;gap:4px">' +
                              '<span style="font-weight:650;color:var(--fg-muted);font-size:10.5px">' + escHtml(f.role) + '</span>' +
                              statusPill +
                            '</div>' +
                            '<div style="font-family:Consolas,monospace;font-weight:650;margin-top:2px">' + escHtml(f.ref) + '</div>' +
                            btnsMarkup +
                        '</div>';
                    }).join("")
                    : '<div style="color:var(--fg-muted)">Decorative / container visual (0 bound data fields).</div>';

                var selMarkup = "";
                if (selVis.selection) {
                    var selTxt = Array.isArray(selVis.selection)
                        ? selVis.selection.join(", ")
                        : (selVis.selection.condition || (Array.isArray(selVis.selection.values) ? selVis.selection.values.join(", ") : String(selVis.selection)));
                    if (selTxt) {
                        selMarkup = '<div style="margin-top:4px"><b style="font-size:11px;color:var(--fg-muted)">Slicer Selection:</b>' +
                            '<div style="margin-top:3px"><span class="dep-chip" style="border-color:var(--accent)">' + escHtml(selTxt) + '</span></div></div>';
                    }
                }
                var txtMarkup = "";
                if (selVis.text) {
                    txtMarkup = '<div style="margin-top:4px;font-size:11.5px;color:var(--fg-muted)"><b>Text:</b> ' + escHtml(midTrunc(selVis.text, 140)) + '</div>';
                }

                var seenFlt = {};
                var allFilters = [];
                (selVis.filters || []).forEach(function (x) { var lbl = "Visual: " + x; if (!seenFlt[lbl]) { seenFlt[lbl] = 1; allFilters.push(lbl); } });
                (pg.filters || []).forEach(function (x) { var lbl = "Page: " + x; if (!seenFlt[lbl]) { seenFlt[lbl] = 1; allFilters.push(lbl); } });
                (item.report_filters || []).forEach(function (x) { var lbl = "Report: " + x; if (!seenFlt[lbl]) { seenFlt[lbl] = 1; allFilters.push(lbl); } });
                var filtHtml = allFilters.length
                    ? '<div style="margin-top:6px"><b style="font-size:11px;color:var(--fg-muted)">Active Visual, Page &amp; Report Filters:</b><div class="lin-list" style="margin-top:4px">' +
                      allFilters.map(function (flt) { return '<span class="dep-chip">' + escHtml(flt) + '</span>'; }).join("") + '</div></div>'
                    : '';

                inspHtml =
                    '<div style="display:flex;gap:5px;flex-wrap:wrap">' +
                      '<span class="badge badge-accent">' + escHtml(selVis.type_label) + '</span>' +
                      (selVis.hidden ? '<span class="badge badge-warn">Hidden</span>' : '') +
                      (selVis.parent ? '<span class="badge">In group</span>' : '') +
                    '</div>' +
                    '<h4>' + escHtml(selVis.title || selVis.type_label) + '</h4>' +
                    '<div style="font-size:11px;color:var(--fg-muted)">Position: ' + selVis.x + ', ' + selVis.y + ' (' + selVis.width + '&times;' + selVis.height + 'px)</div>' +
                    txtMarkup +
                    selMarkup +
                    '<div style="font-weight:650;font-size:11.5px;margin-top:4px">Bound Fields (' + flds.length + ')</div>' +
                    fldsHtml +
                    filtHtml;
            } else {
                inspHtml = '<div style="color:var(--fg-muted)">No visible visuals on this page.</div>';
            }

            var singlePage = pages.length <= 1;
            bodyInner =
                '<div class="xray-explorer' + (singlePage ? ' single-page' : '') + '">' +
                  (singlePage ? '' : (
                    '<div class="xray-pages-pane">' +
                      '<div class="xray-pages-hdr">' +
                        '<span>Report Pages (' + pages.length + ')</span>' +
                        (pages.length > 5 ? '<input type="search" data-xray-page-search="1" value="' + escHtml(pageFilter) + '" placeholder="Filter ' + pages.length + ' pages...">' : '') +
                      '</div>' +
                      '<div class="xray-pages-list"></div>' +
                    '</div>'
                  )) +
                  '<div class="xray-canvas-pane">' +
                    '<div class="xray-canvas-caption">' +
                      '<span>Page: <b>' + escHtml(pg.name) + '</b> (' + Math.round(pg.width || 1280) + '&times;' + Math.round(pg.height || 720) + 'px)</span>' +
                      '<div style="display:flex;align-items:center;gap:8px">' +
                        '<span>Click any visual to inspect bindings</span>' +
                        hidToggleHtml +
                      '</div>' +
                    '</div>' +
                    '<div class="xray-svg-wrap">' + renderWireframeSvg(pg, visuals) + '</div>' +
                  '</div>' +
                  '<div class="xray-inspector-pane">' + inspHtml + '</div>' +
                '</div>';
        }

        if (item.report_measures_html) {
            bodyInner += item.report_measures_html;
        }

        var crossBadge = item.cross_workspace ? '<span class="badge badge-accent">Cross-Workspace Thin Report</span>' : '<span class="badge badge-ok">Same-Workspace Report</span>';
        var brokenTargets = getBrokenTargets(item);
        var brokenBadge = "";
        var brokenStripHtml = "";
        if (brokenTargets.length > 0 || item.broken_count) {
            if (brokenTargets.length > 0) {
                if (activeBrokenCursor >= 0 && activeBrokenCursor < brokenTargets.length) {
                    brokenBadge =
                        '<span class="xray-broken-stepper">' +
                        '<button type="button" data-xray-broken-step="-1" title="Previous broken visual">&larr;</button>' +
                        '<span data-xray-broken-go="' + activeBrokenCursor + '" style="cursor:pointer">! Broken visual ' + (activeBrokenCursor + 1) + ' / ' + brokenTargets.length + ' (' + (item.broken_count || brokenTargets.length) + ' fields)</span>' +
                        '<button type="button" data-xray-broken-step="1" title="Next broken visual">&rarr;</button>' +
                        '</span>';
                } else {
                    brokenBadge =
                        '<button type="button" class="badge-bad-btn" data-xray-broken-go="0" title="Click to jump straight to broken visual #1">' +
                        '! ' + (item.broken_count || brokenTargets.length) + ' broken field(s) in ' + brokenTargets.length + ' visual(s) &bull; Jump &rarr;' +
                        '</button>';
                }
                brokenStripHtml =
                    '<div style="padding:8px 14px;border-radius:9px;background:var(--bad-bg);border:1px solid rgba(185,28,28,0.28);display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px">' +
                    '<b style="color:var(--bad)">Broken Field Bindings (' + brokenTargets.length + '):</b>' +
                    brokenTargets.slice(0, 12).map(function (bt, bi) {
                        var activeStyle = bi === activeBrokenCursor ? 'border-color:var(--bad);background:var(--surface);font-weight:700' : '';
                        return '<button type="button" class="dep-chip" style="cursor:pointer;' + activeStyle + '" data-xray-broken-go="' + bi + '">' +
                            escHtml(midTrunc(bt.pageName, 18) + ' > ' + midTrunc(bt.visTitle, 22)) + ' (' + bt.fieldCount + ')' +
                            '</button>';
                    }).join("") +
                    '</div>';
            } else {
                brokenBadge = '<span class="badge badge-bad">' + item.broken_count + ' broken field(s)</span>';
                if (item.broken_refs && item.broken_refs.length) {
                    brokenStripHtml =
                        '<div style="padding:8px 14px;border-radius:9px;background:var(--bad-bg);border:1px solid rgba(185,28,28,0.28);display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px">' +
                        '<b style="color:var(--bad)">Broken Filter / DAX Bindings (' + item.broken_refs.length + '):</b>' +
                        item.broken_refs.slice(0, 12).map(function (br) {
                            return '<span class="dep-chip" style="border-color:var(--bad);color:var(--bad);background:var(--surface)">' +
                                escHtml((br.page || "Report") + " > " + (br.visual || "Filter") + ": " + (br.ref || "")) +
                                '</span>';
                        }).join("") +
                        '</div>';
                }
            }
        }
        var shadowBadge = item.report_measures_count ? '<span class="badge badge-warn">' + item.report_measures_count + ' report-level DAX</span>' : '';

        drawerEl.innerHTML =
            '<div class="xray-header">' +
              '<div>' +
                '<div class="model-meta">' + crossBadge + '<span class="badge">Workspace: ' + escHtml(item.workspace) + '</span>' + brokenBadge + shadowBadge + '</div>' +
                '<h3>' + escHtml(item.name) + '</h3>' +
                '<div style="font-size:12px;color:var(--fg-muted)">Bound Semantic Model: <b>' + escHtml(item.model_name) + '</b> (' + escHtml(item.model_workspace) + ')</div>' +
              '</div>' +
              '<div class="xray-header-controls">' +
                navHtml +
                '<button type="button" class="lin-btn" data-xray-close="1">Close (Esc)</button>' +
              '</div>' +
            '</div>' +
            '<div class="xray-body">' + brokenStripHtml + bodyInner + '</div>';

        renderPagesListOnly();
    }

    // Interactive Clickable Power Query M Step-Through (UTF-16 range highlighter)
    document.addEventListener("click", function (e) {
        var stepBtn = e.target.closest("button.pq-step-btn[data-pq-step]");
        if (stepBtn) {
            var wrap = stepBtn.closest(".pq-interactive-wrap");
            if (!wrap) return;
            var metaEl = wrap.querySelector("script.pq-meta-json");
            var inspEl = wrap.querySelector(".pq-step-inspector");
            var preEl = wrap.querySelector("pre.pq-m-pre");
            var detEl = wrap.querySelector("details.m-script-toggle");
            if (!metaEl || !inspEl || !preEl) return;

            var meta;
            try { meta = JSON.parse(metaEl.textContent || "{}"); } catch (err) { return; }
            var idx = parseInt(stepBtn.getAttribute("data-pq-step"), 10);
            var steps = meta.steps || [];
            var raw = String(meta.raw || "");
            if (isNaN(idx) || !steps[idx]) return;

            if (!preEl._origHtml) preEl._origHtml = preEl.innerHTML;

            var wasActive = stepBtn.classList.contains("is-active");
            wrap.querySelectorAll("button.pq-step-btn").forEach(function (b) { b.classList.remove("is-active"); });
            if (wasActive) {
                inspEl.style.display = "none";
                preEl.innerHTML = preEl._origHtml;
                return;
            }

            stepBtn.classList.add("is-active");
            var st = steps[idx];
            var detChips = (st.details || []).map(function (d) {
                return '<span class="dep-chip" style="background:var(--surface)">' + escHtml(d) + '</span>';
            }).join(" ");
            inspEl.innerHTML =
                '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">' +
                  '<span><b>Step ' + st.index + ': ' + escHtml(st.name) + '</b> <span class="badge">' + escHtml(st.op) + '</span></span>' +
                  '<span style="font-size:11px;color:var(--fg-muted)">Click step again to clear highlight</span>' +
                '</div>' +
                '<div style="margin-top:4px">' + escHtml(st.summary || st.op) + '</div>' +
                (detChips ? '<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:6px">' + detChips + '</div>' : '');
            inspEl.style.display = "";

            if (typeof st.start === "number" && typeof st.end === "number" && st.end > st.start && st.end <= raw.length) {
                preEl.innerHTML =
                    escHtml(raw.slice(0, st.start)) +
                    '<mark class="pq-span-mark">' + escHtml(raw.slice(st.start, st.end)) + '</mark>' +
                    escHtml(raw.slice(st.end));
                if (detEl) detEl.open = true;
                var mk = preEl.querySelector("mark.pq-span-mark");
                if (mk && mk.scrollIntoView) {
                    setTimeout(function () { mk.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, 30);
                }
            }
            return;
        }

        var btn = e.target.closest("[data-open-xray]");
        if (!btn) return;
        e.preventDefault();
        openDrawer(btn.getAttribute("data-open-xray"), btn.hasAttribute("data-xray-jump-broken"));
    });

    window.PbiOpenXray = openDrawer;
})();
