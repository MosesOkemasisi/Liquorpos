(() => {
  const root = document.getElementById("pos");
  if (!root) return;
  const csrf = root.dataset.csrf;
  const { money, esc } = window.Pay;
  const $ = (sel) => root.querySelector(sel);

  let products = [];
  const cart = new Map(); // product id -> { p, qty }
  let sale = null; // the sale currently awaiting M-Pesa
  let stopPolling = null;

  const el = {
    search: $("#search"), grid: $("#grid"), lines: $("#lines"), total: $("#total"),
    charge: $("#charge"), age: $("#age"), phone: $("#phone"), tendered: $("#tendered"),
    cashAmount: $("#cash_amount"), change: $("#change"), cashBox: $("#cash-box"),
    mpesaBox: $("#mpesa-box"), splitBox: $("#split-box"),
    overlay: document.getElementById("result"), dialog: document.getElementById("dialog"),
    toast: document.getElementById("toast"),
  };

  const total = () => [...cart.values()].reduce((s, l) => s + l.p.price * l.qty, 0);
  const method = () => root.querySelector("input[name=method]:checked").value;

  function toast(msg) {
    el.toast.textContent = msg;
    el.toast.style.display = "block";
    clearTimeout(toast.t);
    toast.t = setTimeout(() => (el.toast.style.display = "none"), 3000);
  }

  /* ---------- products ---------- */
  async function loadProducts(q = "") {
    const resp = await fetch(root.dataset.productsUrl + "?q=" + encodeURIComponent(q), { credentials: "same-origin" });
    products = (await resp.json()).products;
    renderGrid();
  }

  function renderGrid() {
    el.grid.innerHTML = products.map((p) => `
      <button class="tile ${p.stock <= 5 ? "low" : ""}" data-id="${p.id}" ${p.stock === 0 ? "disabled" : ""}>
        ${p.image ? `<img class="tile-img" src="${esc(p.image)}" alt="" loading="lazy">` : '<span class="tile-img empty"></span>'}
        <span class="name">${esc(p.name)}</span>
        <span class="stock">${p.stock === 0 ? "Out of stock" : p.stock + " in stock"}</span>
        <span class="price">${money(p.price)}</span>
      </button>`).join("") || '<p class="muted">No products found.</p>';
  }

  function addToCart(p) {
    const line = cart.get(p.id) || { p, qty: 0 };
    if (line.qty + 1 > p.stock) return toast(`Only ${p.stock} of ${p.name} in stock`);
    line.qty += 1;
    cart.set(p.id, line);
    renderCart();
  }

  /* ---------- cart ---------- */
  function renderCart() {
    el.lines.innerHTML = [...cart.values()].map(({ p, qty }) => `
      <div class="cart-line">
        <div>${esc(p.name)}<div class="muted">${money(p.price)} each</div></div>
        <div class="num"><strong>${money(p.price * qty)}</strong></div>
        <div class="qty">
          <button data-act="dec" data-id="${p.id}">−</button><span>${qty}</span>
          <button data-act="inc" data-id="${p.id}">+</button>
        </div>
        <div style="text-align:right"><button class="small ghost" data-act="del" data-id="${p.id}">Remove</button></div>
      </div>`).join("") || '<p class="muted">Cart is empty. Tap a product or scan a barcode.</p>';
    el.total.textContent = money(total());
    updatePayment();
  }

  function updatePayment() {
    const m = method();
    el.cashBox.style.display = m === "cash" ? "block" : "none";
    el.splitBox.style.display = m === "split" ? "block" : "none";
    el.mpesaBox.style.display = m === "cash" ? "none" : "block";
    const t = total();
    const tendered = Number(el.tendered.value || 0);
    el.change.textContent = m === "cash" && tendered >= t && t > 0 ? "Change: " + money(tendered - t) : "";
    let ok = cart.size > 0 && el.age.checked;
    if (m === "cash") ok = ok && tendered >= t;
    if (m === "split") { const c = Number(el.cashAmount.value || 0); ok = ok && c > 0 && c < t; }
    el.charge.disabled = !ok;
    el.charge.textContent = cart.size ? "Charge " + money(t) : "Charge";
  }

  /* ---------- result dialog ---------- */
  function show(html) { el.dialog.innerHTML = html; el.overlay.classList.add("open"); }
  function hide() { el.overlay.classList.remove("open"); }

  function newSale() {
    if (stopPolling) stopPolling();
    cart.clear(); sale = null;
    el.tendered.value = ""; el.cashAmount.value = ""; el.phone.value = ""; el.age.checked = false;
    hide(); renderCart(); loadProducts(el.search.value); el.search.focus();
  }

  function showPaid(info) {
    show(`<div class="big">✅</div><h2>Payment received</h2>
      <p class="muted">${esc(info.receipt_no)}${info.mpesa ? " · M-Pesa " + esc(info.mpesa) : ""}</p>
      ${info.change ? `<p class="big">Change ${money(info.change)}</p>` : ""}
      <div class="row" style="margin-top:1rem">
        <a class="btn" target="_blank" href="${info.receipt_url}?print=1">Print receipt</a>
        <button class="primary" id="new-sale">New sale</button>
      </div>`);
    document.getElementById("new-sale").onclick = newSale;
  }

  function showWaiting(phone) {
    show(`<div class="spinner"></div><h2>Waiting for customer…</h2>
      <p class="muted">An M-Pesa prompt was sent to ${esc(phone || "the customer")}. Ask them to enter their PIN.</p>
      <p class="muted" id="wait-note"></p>
      <button class="danger" id="cancel-sale">Cancel sale</button>`);
    document.getElementById("cancel-sale").onclick = cancelSale;
  }

  function showFailed(message) {
    show(`<div class="big">⚠️</div><h2>M-Pesa not completed</h2>
      <p class="muted">${esc(message || "The payment was not approved.")}</p>
      <div class="field" style="text-align:left"><label>Phone number to try again</label>
        <input id="retry-phone" inputmode="tel" value="${esc(el.phone.value)}"></div>
      <p id="retry-err" class="muted" style="color:var(--red)"></p>
      <div class="row">
        <button class="primary" id="retry">Send prompt again</button>
        <button class="danger" id="cancel-sale">Cancel sale</button>
      </div>`);
    document.getElementById("cancel-sale").onclick = cancelSale;
    document.getElementById("retry").onclick = retry;
  }

  function startPolling() {
    if (stopPolling) stopPolling();
    stopPolling = window.Pay.poll(sale.status_url, {
      onPending: (d) => { const n = document.getElementById("wait-note"); if (n && d.balance) n.textContent = "Outstanding: " + money(d.balance); },
      onPaid: (d) => showPaid({ receipt_no: sale.receipt_no, receipt_url: sale.receipt_url, mpesa: d.payment && d.payment.receipt, change: 0 }),
      onFailed: (d) => showFailed(d.payment && d.payment.desc),
    });
  }

  async function retry() {
    const phone = document.getElementById("retry-phone").value;
    const r = await window.Pay.post(sale.retry_url, { phone }, csrf);
    if (!r.ok) { document.getElementById("retry-err").textContent = r.data.error; return; }
    el.phone.value = phone;
    showWaiting(phone);
    startPolling();
  }

  async function cancelSale() {
    if (stopPolling) stopPolling();
    const r = await window.Pay.post(sale.cancel_url, {}, csrf);
    if (!r.ok) { toast(r.data.error); return; }
    sale = null; hide(); toast("Sale cancelled. Stock returned.");
    loadProducts(el.search.value);
  }

  /* ---------- checkout ---------- */
  async function charge() {
    el.charge.disabled = true;
    const m = method();
    const payload = {
      method: m, age_confirmed: el.age.checked, phone: el.phone.value,
      cash_tendered: el.tendered.value, cash_amount: el.cashAmount.value,
      items: [...cart.values()].map((l) => ({ id: l.p.id, qty: l.qty })),
    };
    const r = await window.Pay.post(root.dataset.checkoutUrl, payload, csrf);
    if (!r.ok) { toast(r.data.error || "Could not complete the sale."); updatePayment(); return; }
    const d = r.data;
    sale = d;
    if (d.status === "paid") return showPaid({ receipt_no: d.receipt_no, receipt_url: d.receipt_url, change: d.change });
    showWaiting(el.phone.value);
    startPolling();
  }

  /* ---------- events ---------- */
  el.grid.addEventListener("click", (e) => {
    const b = e.target.closest(".tile");
    if (b) addToCart(products.find((p) => p.id === Number(b.dataset.id)));
  });
  el.lines.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const line = cart.get(Number(b.dataset.id));
    if (b.dataset.act === "inc") return addToCart(line.p);
    if (b.dataset.act === "dec") { line.qty -= 1; if (line.qty <= 0) cart.delete(line.p.id); }
    if (b.dataset.act === "del") cart.delete(line.p.id);
    renderCart();
  });

  let timer;
  el.search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => loadProducts(el.search.value.trim()), 200); });
  // Barcode scanners type the code then press Enter: add the exact match straight away.
  el.search.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = el.search.value.trim();
    if (!q) return;
    await loadProducts(q);
    const exact = products.find((p) => p.barcode === q || p.sku.toLowerCase() === q.toLowerCase()) || (products.length === 1 ? products[0] : null);
    if (exact && exact.stock > 0) { addToCart(exact); el.search.value = ""; loadProducts(""); }
  });

  root.querySelectorAll("input[name=method]").forEach((r) => r.addEventListener("change", updatePayment));
  [el.age, el.tendered, el.cashAmount].forEach((i) => i.addEventListener("input", updatePayment));
  $("#exact").addEventListener("click", () => { el.tendered.value = total(); updatePayment(); });
  el.charge.addEventListener("click", charge);

  renderCart();
  loadProducts();
  el.search.focus();
})();
