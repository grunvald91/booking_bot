document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
        const target = document.querySelector(link.getAttribute("href"));
        if (!target) {
            return;
        }
        event.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
});

const topbar = document.querySelector(".topbar");
window.addEventListener("scroll", () => {
    topbar.classList.toggle("is-scrolled", window.scrollY > 12);
});

function applyDesktopLinks() {
    const isTelegramWebApp = Boolean(window.Telegram?.WebApp?.initData);
    const isDesktop = window.matchMedia("(min-width: 721px)").matches;

    document.querySelectorAll("[data-desktop-href]").forEach((link) => {
        if (!link.dataset.telegramHref) {
            link.dataset.telegramHref = link.getAttribute("href") || "";
        }

        link.setAttribute(
            "href",
            isDesktop && !isTelegramWebApp ? link.dataset.desktopHref : link.dataset.telegramHref
        );
    });
}

applyDesktopLinks();
window.addEventListener("resize", applyDesktopLinks);
