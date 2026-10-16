const $ = s => document.querySelector(s), charts = {};
const inr = n => "₹" + Number(n).toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const draw = (id, cfg) => { charts[id]?.destroy(); charts[id] = new Chart($("#" + id), cfg); };

async function load() {
  const res = await fetch("/api/summary?month=" + $("#month").value);
  if (!res.ok) return;
  const d = await res.json();
  $("#k-inc").textContent = inr(d.income); $("#k-exp").textContent = inr(d.expense);
  $("#k-net").textContent = inr(d.net); $("#k-rate").textContent = d.savings_rate + "%";
  $("#alerts").innerHTML = d.alerts.map(a =>
    `<div class="alert ${a.status}">${a.category}: ${a.pct >= 100 ? "over budget" : "nearing limit"} (${a.pct}% of ${inr(a.limit)})</div>`).join("");
  $("#budgets").innerHTML = d.budgets.length ? d.budgets.map(b =>
    `<div class="budget ${b.status}"><b>${b.category}</b> ${inr(b.spent)} of ${inr(b.limit)}<progress max="100" value="${Math.min(b.pct, 100)}"></progress></div>`).join("")
    : '<p class="empty">No budgets set yet.</p>';
  draw("cat", {type: "doughnut", data: {labels: Object.keys(d.by_category),
    datasets: [{data: Object.values(d.by_category), backgroundColor: ["#0f6b5c","#e07a1f","#3b6fb6","#b3261e","#7a5195","#9a8f2b","#2a9d8f","#8d99ae","#c1666b","#5c7a29"]}]}});
  draw("trend", {type: "bar", data: {labels: d.trend.labels, datasets: [
    {label: "Income", data: d.trend.income, backgroundColor: "#0f6b5c"},
    {label: "Expenses", data: d.trend.expense, backgroundColor: "#b3261e"}]}});
}
$("#month").value = new Date().toISOString().slice(0, 7);
$("#month").addEventListener("change", load);
load();
