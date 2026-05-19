/* ============================================================
   ReachSwim — vanilla JS
   No frameworks. No dependencies.
   ============================================================ */

(function () {
  "use strict";

  // --- Scroll-aware nav ---
  function initNav() {
    const nav = document.getElementById("site-nav");
    if (!nav) return;
    
    // Django renders booleans as "True"/"False" strings
    const hasHero = document.body.dataset.hasHero === "True";
    
    // On pages without heroes, immediately apply scrolled styling
    if (!hasHero) {
      nav.classList.add("scrolled");
    }
    
    const onScroll = () => {
      if (hasHero) {
        // Only toggle based on scroll on pages with heroes
        nav.classList.toggle("scrolled", window.scrollY > 24);
      } else {
        // Always keep scrolled on pages without heroes
        nav.classList.add("scrolled");
      }
    };
    
    // Also listen to scroll events
    window.addEventListener("scroll", onScroll, { passive: true });
  }
  
  // Call immediately if DOM is ready, otherwise wait for DOMContentLoaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initNav);
  } else {
    initNav();
  }
  
  // Also call after a small delay to ensure everything is ready
  setTimeout(initNav, 100);

  // --- Scroll reveal (IntersectionObserver) ---
  const reveals = document.querySelectorAll(".reveal");
  if (reveals.length && "IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    reveals.forEach((el) => io.observe(el));
    // Kick elements already in viewport on load (observer is async)
    requestAnimationFrame(() => {
      reveals.forEach((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight && rect.bottom > 0) {
          el.classList.add("in");
          io.unobserve(el);
        }
      });
    });
  } else {
    // Fallback: show everything
    reveals.forEach((el) => el.classList.add("in"));
  }

  // --- FAQ accordion ---
  document.querySelectorAll(".faq-trigger").forEach((btn) => {
    btn.addEventListener("click", () => {
      const expanded = btn.getAttribute("aria-expanded") === "true";
      const answer = btn.nextElementSibling;

      // Close all
      document.querySelectorAll(".faq-trigger").forEach((b) => {
        b.setAttribute("aria-expanded", "false");
        b.nextElementSibling.classList.remove("faq-answer--open");
      });

      // Toggle clicked
      if (!expanded) {
        btn.setAttribute("aria-expanded", "true");
        answer.classList.add("faq-answer--open");
      }
    });
  });

  // --- Smooth scroll for anchor links ---
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const target = document.querySelector(a.getAttribute("href"));
      if (target) {
        e.preventDefault();
        window.scrollTo({
          top: target.getBoundingClientRect().top + window.scrollY - 80,
          behavior: "smooth",
        });
      }
    });
  });
  // --- Cart drawer toggle ---
  window.toggleCartDrawer = function () {
    const drawer = document.getElementById("cart-drawer");
    const overlay = document.getElementById("cart-overlay");
    if (!drawer) return;
    const open = drawer.classList.toggle("open");
    if (overlay) overlay.classList.toggle("open", open);
    document.body.classList.toggle("cart-open", open);

    // Load cart contents when opening
    if (open) {
      fetch("/cart/")
        .then((r) => r.text())
        .then((html) => {
          const content = document.getElementById("cart-drawer-content");
          if (content) content.innerHTML = html;
        })
        .catch(() => {});
    }
  };

  // --- Shared CSRF helper ---
  function getCSRF() {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfInput = document.querySelector("[name=csrfmiddlewaretoken]");
    return csrfMeta
      ? csrfMeta.content
      : csrfInput
        ? csrfInput.value
        : document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  // --- Open cart drawer + update its contents ---
  function openDrawerWithHTML(html) {
    const drawer = document.getElementById("cart-drawer-content");
    if (drawer) drawer.innerHTML = html;

    const drawerEl = document.getElementById("cart-drawer");
    const overlayEl = document.getElementById("cart-overlay");
    if (drawerEl && !drawerEl.classList.contains("open")) {
      drawerEl.classList.add("open");
      if (overlayEl) overlayEl.classList.add("open");
      document.body.classList.add("cart-open");
    }

    document.body.dispatchEvent(new Event("cartUpdated"));
  }

  // --- Add booking to cart (called from slot buttons) ---
  window.addToCart = function (btn) {
    const payload = {
      session_type_id: btn.dataset.sessionType,
      location_id: btn.dataset.location,
      date: btn.dataset.date,
      start_time: btn.dataset.start,
      end_time: btn.dataset.end,
      price_pence: btn.dataset.price,
      label: btn.dataset.label || "Session",
    };

    fetch("/cart/add/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCSRF() },
      body: JSON.stringify(payload),
    })
      .then((r) => r.text())
      .then((html) => {
        openDrawerWithHTML(html);
        btn.textContent = "Added ✓";
        btn.disabled = true;
        setTimeout(() => { btn.textContent = "Add to cart"; btn.disabled = false; }, 1500);
      })
      .catch((err) => console.error("Cart add failed:", err));
  };

  // --- Add product to cart (called from shop product cards) ---
  window.addProductToCart = function (btn) {
    const payload = {
      product_id: btn.dataset.productId,
      name: btn.dataset.name,
      color: btn.dataset.color || "",
      price_pence: btn.dataset.price,
      qty: 1,
      photo_class: btn.dataset.photoClass || "",
      image_url: btn.dataset.image || "",
    };

    fetch("/cart/add-product/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCSRF() },
      body: JSON.stringify(payload),
    })
      .then((r) => r.text())
      .then((html) => {
        openDrawerWithHTML(html);
        btn.textContent = "Added ✓";
        btn.disabled = true;
        setTimeout(() => { btn.textContent = "Add to cart"; btn.disabled = false; }, 1500);
      })
      .catch((err) => console.error("Product add failed:", err));
  };

  // --- Update product quantity in cart ---
  window.updateCartQty = function (productId, qty) {
    fetch("/cart/update-qty/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCSRF() },
      body: JSON.stringify({ product_id: productId, qty: qty }),
    })
      .then((r) => r.text())
      .then((html) => {
        const drawer = document.getElementById("cart-drawer-content");
        if (drawer) drawer.innerHTML = html;
        document.body.dispatchEvent(new Event("cartUpdated"));
      })
      .catch((err) => console.error("Cart qty update failed:", err));
  };

  // --- Shop filter tabs ---
  document.querySelectorAll("[data-filter-group]").forEach(function (group) {
    var tabs = group.querySelectorAll("[data-filter]");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        var filter = tab.dataset.filter;
        var cards = document.querySelectorAll("[data-category]");
        cards.forEach(function (card) {
          if (filter === "all" || card.dataset.category === filter) {
            card.style.display = "";
          } else {
            card.style.display = "none";
          }
        });
      });
    });
  });
})();
