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

const connectModal = document.querySelector("[data-connect-modal]");
const connectForm = document.querySelector("[data-connect-form]");
const connectStatus = document.querySelector("[data-connect-form-status]");
const openConnectButtons = document.querySelectorAll("[data-open-connect-form]");
const closeConnectButtons = document.querySelectorAll("[data-close-connect-form]");

function setConnectStatus(message, type = "") {
    if (!connectStatus) {
        return;
    }

    connectStatus.textContent = message;
    connectStatus.classList.toggle("is-error", type === "error");
    connectStatus.classList.toggle("is-success", type === "success");
}

function openConnectModal() {
    if (!connectModal || !connectForm) {
        return;
    }

    connectModal.hidden = false;
    document.body.classList.add("modal-open");
    setConnectStatus("");
    connectForm.elements.name?.focus();
}

function closeConnectModal() {
    if (!connectModal) {
        return;
    }

    connectModal.hidden = true;
    document.body.classList.remove("modal-open");
}

openConnectButtons.forEach((button) => {
    button.addEventListener("click", openConnectModal);
});

closeConnectButtons.forEach((button) => {
    button.addEventListener("click", closeConnectModal);
});

connectModal?.addEventListener("click", (event) => {
    if (event.target === connectModal) {
        closeConnectModal();
    }
});

window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && connectModal && !connectModal.hidden) {
        closeConnectModal();
    }
});

connectForm?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const formData = new FormData(connectForm);
    const payload = {
        name: String(formData.get("name") || "").trim(),
        phone: String(formData.get("phone") || "").trim(),
        email: String(formData.get("email") || "").trim(),
        comment: String(formData.get("comment") || "").trim(),
    };

    if (!payload.name) {
        setConnectStatus("Укажите имя", "error");
        connectForm.elements.name?.focus();
        return;
    }

    if (!payload.phone && !payload.email) {
        setConnectStatus("Укажите телефон или email", "error");
        connectForm.elements.phone?.focus();
        return;
    }

    const submitButton = connectForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    setConnectStatus("Отправляем заявку...");

    try {
        const response = await fetch("/api/landing/connect-request", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));

        if (!response.ok || !result.success) {
            throw new Error(result.error || "Не удалось отправить заявку");
        }

        connectForm.reset();
        setConnectStatus("Заявка отправлена. Мы скоро свяжемся с вами.", "success");
    } catch (error) {
        setConnectStatus(error.message || "Не удалось отправить заявку", "error");
    } finally {
        submitButton.disabled = false;
    }
});
