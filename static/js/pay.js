/* Shared helpers: JSON POST with CSRF and an M-Pesa payment status poller. */
window.Pay = {
  async post(url, body, csrf) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, Accept: "application/json" },
      body: JSON.stringify(body || {}),
      credentials: "same-origin",
    });
    let data = {};
    try { data = await resp.json(); } catch (e) { /* non-JSON error page */ }
    if (!resp.ok && !data.error) data.error = "Something went wrong (" + resp.status + ").";
    return { ok: resp.ok && data.ok !== false, data };
  },

  /* Poll the status URL every few seconds. Calls exactly one of onPaid / onFailed, then stops. */
  poll(url, { onPending, onPaid, onFailed, interval = 3000, maxMs = 330000 }) {
    let stopped = false;
    const started = Date.now();
    const tick = async () => {
      if (stopped) return;
      try {
        const resp = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
        const d = await resp.json();
        if (d.sale_status === "paid") { stopped = true; return onPaid(d); }
        if (d.payment && d.payment.status === "failed") { stopped = true; return onFailed(d); }
        if (["cancelled", "failed", "voided"].includes(d.sale_status)) { stopped = true; return onFailed(d); }
        if (onPending) onPending(d);
      } catch (e) { /* network blip: keep trying */ }
      if (Date.now() - started > maxMs) {
        stopped = true;
        return onFailed({ payment: { desc: "Timed out waiting for the customer to approve." } });
      }
      setTimeout(tick, interval);
    };
    tick();
    return () => { stopped = true; };
  },

  money(n) { return "KES " + Number(n).toLocaleString("en-KE"); },
  esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  },
};
