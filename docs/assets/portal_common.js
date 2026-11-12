
(function () {
    var saved = localStorage.getItem("pbidoc-v1-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);

    // Reveal "Back to Scanner & Setup" switcher only when served by the local Studio HTTP server
    document.addEventListener("DOMContentLoaded", function () {
        var isLocalStudio = (location.protocol === "http:" || location.protocol === "https:") &&
            (location.hostname === "127.0.0.1" || location.hostname === "localhost");
        if (isLocalStudio) {
            document.querySelectorAll(".studio-only-link").forEach(function (el) {
                el.style.display = "";
            });
        }
    });

    document.addEventListener("click", function (e) {
        var expBtn = e.target.closest("[data-details-toggle]");
        if (expBtn) {
            var scopeId = expBtn.getAttribute("data-details-toggle");
            var shouldOpen = expBtn.getAttribute("data-open") === "1";
            var root = document.getElementById(scopeId) || document;
            root.querySelectorAll("details").forEach(function (d) { d.open = shouldOpen; });
            return;
        }
        var measureJump = e.target.closest('a[href^="#measure-"]');
        if (measureJump) {
            var cardsBtn = document.querySelector('[data-dax-view="cards"]');
            if (cardsBtn && !cardsBtn.classList.contains("active")) {
                cardsBtn.click();
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
        var themeBtn = e.target.closest("[data-toggle-theme]");
        if (themeBtn) {
            var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", cur);
            localStorage.setItem("pbidoc-v1-theme", cur);
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
    });
})();
