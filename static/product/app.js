document.documentElement.classList.add("js");

const architectureTabs = Array.from(document.querySelectorAll('[role="tab"][aria-controls]'));

function activateArchitectureTab(tab, moveFocus = false) {
  architectureTabs.forEach((item) => {
    const active = item === tab;
    const panel = document.getElementById(item.getAttribute("aria-controls"));
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
    item.tabIndex = active ? 0 : -1;
    if (panel) panel.hidden = !active;
  });

  if (moveFocus) tab.focus();
}

architectureTabs.forEach((tab, index) => {
  tab.addEventListener("click", () => activateArchitectureTab(tab));
  tab.addEventListener("keydown", (event) => {
    let nextIndex;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % architectureTabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + architectureTabs.length) % architectureTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = architectureTabs.length - 1;
    if (nextIndex === undefined) return;
    event.preventDefault();
    activateArchitectureTab(architectureTabs[nextIndex], true);
  });
});

const revealItems = document.querySelectorAll(".reveal");

if ("IntersectionObserver" in window) {
  const revealObserver = new IntersectionObserver(
    (entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { rootMargin: "0px 0px -8%", threshold: 0.08 },
  );

  revealItems.forEach((item) => revealObserver.observe(item));
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"));
}

const lightbox = document.querySelector(".lightbox");
const lightboxImage = lightbox.querySelector("img");
const lightboxCaption = lightbox.querySelector("figcaption");
const closeButton = lightbox.querySelector(".lightbox-close");

document.querySelectorAll("[data-image]").forEach((trigger) => {
  trigger.addEventListener("click", () => {
    lightboxImage.src = trigger.querySelector("img")?.src || trigger.dataset.image;
    lightboxImage.alt = trigger.querySelector("img")?.alt || "产品界面截图";
    lightboxCaption.textContent = trigger.dataset.caption || "记忆宫殿产品界面";
    lightbox.showModal();
    document.body.classList.add("lightbox-open");
  });
});

function closeLightbox() {
  if (lightbox.open) lightbox.close();
}

closeButton.addEventListener("click", closeLightbox);

lightbox.addEventListener("click", (event) => {
  if (event.target === lightbox) closeLightbox();
});

lightbox.addEventListener("close", () => {
  document.body.classList.remove("lightbox-open");
  lightboxImage.removeAttribute("src");
});
