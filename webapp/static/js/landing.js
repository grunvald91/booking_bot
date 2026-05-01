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
