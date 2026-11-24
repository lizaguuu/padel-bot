(async () => {
  // 🎾 Padel-бот во вкладке браузера: Mitte Cabrio → Telegram.
  // Работает, пока открыта вкладка playtomic.com. Проверка раз в 90 секунд.
  const TENANT = "24234663-6264-471c-91fe-20fa80cf52d5";
  const CLUB_URL = "https://playtomic.com/clubs/mitte-the-cabrio";
  const CHAT_ID = "-5365069771";
  const EVERY_SEC = 90, DAYS_AHEAD = 13, WEEKDAY_FROM = 17 * 60 + 30;
  const DURATIONS = [60, 90, 120];
  const SINGLE = ["d2731550-e8ad-4d09-8ab4-0bb633c80b50", "759403bb-5f15-40f9-aca4-445ae55ea0f3", "0b972e5b-874e-4be2-98a5-3260d0433d16"];
  const WD = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
  const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };

  if (!location.hostname.endsWith("playtomic.com")) {
    if (confirm("Бот работает только на сайте Playtomic. Открыть страницу клуба? Потом нажми закладку ещё раз.")) location.href = CLUB_URL;
    return;
  }
  if (window.__padelBot) { alert("🎾 Бот уже работает в этой вкладке."); return; }

  let token = LS("padelBotToken");
  if (!token) {
    token = (prompt("Первый запуск. Вставь токен бота от @BotFather:") || "").replace(/\s+/g, "");
    if (!token) return;
    const me = await fetch(`https://api.telegram.org/bot${token}/getMe`).then(r => r.json()).catch(() => ({}));
    if (!me.ok) { alert("❌ Telegram не принял этот токен. Проверь его и нажми закладку ещё раз."); return; }
    LS("padelBotToken", token);
  }

  const box = document.createElement("div");
  box.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;background:#111;color:#fff;font:13px/1.4 -apple-system,sans-serif;padding:10px 14px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.3);max-width:280px";
  const status = document.createElement("div");
  const stop = document.createElement("button");
  stop.textContent = "Остановить";
  stop.style.cssText = "margin-top:6px;background:#333;color:#fff;border:0;border-radius:6px;padding:3px 8px;cursor:pointer";
  box.append(status, stop);
  document.body.appendChild(box);
  const show = t => { status.innerHTML = "🎾 <b>Padel-бот работает</b><br>" + t + "<br><small>Не закрывай эту вкладку</small>"; };

  const send = text => fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    body: new URLSearchParams({ chat_id: CHAT_ID, text, parse_mode: "HTML", disable_web_page_preview: "true" })
  }).then(r => r.json()).catch(e => ({ ok: false, description: String(e) }));

  const berlin = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short" });
  const parts = d => Object.fromEntries(berlin.formatToParts(d).map(p => [p.type, p.value]));
  const local = d => { const p = parts(d); return { date: `${p.year}-${p.month}-${p.day}`, hm: `${p.hour}:${p.minute}`, min: +p.hour * 60 + +p.minute, wd: ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].indexOf(p.weekday) }; };

  async function collect() {
    const now = new Date(), found = {};
    let ok = 0, lastErr = "";
    for (let i = 0; i <= DAYS_AHEAD; i++) {
      const day = local(new Date(now.getTime() + i * 864e5)).date;
      try {
        const r = await fetch(`/api/clubs/availability?tenant_id=${TENANT}&date=${day}&sport_id=PADEL`, { headers: { Accept: "application/json" } });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json(); ok++;
        for (const b of data || []) {
          if (SINGLE.includes(b.resource_id)) continue;
          for (const s of b.slots || []) {
            const t = new Date(`${b.start_date}T${s.start_time}Z`);
            if (t <= now || !DURATIONS.includes(s.duration)) continue;
            const L = local(t);
            if (L.date !== day) continue;
            const weekend = L.wd === 0 || L.wd === 6;
            if (!weekend && L.min < WEEKDAY_FROM) continue;
            found[`${b.resource_id}|${L.date}T${L.hm}|${s.duration}`] = { date: L.date, wd: L.wd, hm: L.hm, dur: s.duration, price: s.price };
          }
        }
      } catch (e) { lastErr = e.message; }
      await new Promise(r => setTimeout(r, 400));
    }
    if (!ok) throw new Error("Playtomic не ответил: " + lastErr);
    return found;
  }

  function format(list) {
    const days = {};
    list.sort((a, b) => (a.date + a.hm + a.dur).localeCompare(b.date + b.hm + b.dur)).forEach(s => {
      const [y, m, d] = s.date.split("-");
      const label = `${WD[s.wd]} ${d}.${m}`;
      const key = `${s.hm} · ${s.dur} мин`;
      ((days[label] ||= {})[key] ||= []).push(s);
    });
    return Object.entries(days).map(([label, times]) =>
      `\n📅 <b>${label}</b>\n` + Object.entries(times).map(([k, arr]) =>
        `  • ${k} · ${arr.length} ${arr.length === 1 ? "корт" : arr.length < 5 ? "корта" : "кортов"} · ${arr[0].price}`).join("\n")).join("\n");
  }

  async function sendLong(text) {
    while (text.length > 3800) {
      let cut = text.lastIndexOf("\n📅", 3800); if (cut <= 0) cut = 3800;
      await send(text.slice(0, cut)); text = text.slice(cut);
    }
    return send(text);
  }

  let errorSent = false;
  async function tick() {
    try {
      const cur = await collect();
      const prevRaw = LS("padelBotSeen");
      const prev = prevRaw ? JSON.parse(prevRaw) : null;
      if (!prev) {
        const r = await sendLong(`🎾 <b>Mitte Cabrio</b>: бот запущен в браузере.\nСейчас свободно ${Object.keys(cur).length} подходящих слотов (будни с 17:30, выходные весь день).` + format(Object.values(cur)) + `\n\nДальше пишу только о новых освободившихся.\n👉 ${CLUB_URL}`);
        if (!r.ok) throw new Error("Telegram: " + r.description);
      } else {
        const fresh = Object.keys(cur).filter(k => !(k in prev));
        if (fresh.length) {
          const r = await sendLong(`🎾 <b>Освободилось в Mitte Cabrio!</b>` + format(fresh.map(k => cur[k])) + `\n\n👉 <a href="${CLUB_URL}">Забронировать в Playtomic</a>`);
          if (!r.ok) throw new Error("Telegram: " + r.description);
        }
      }
      LS("padelBotSeen", JSON.stringify(cur));
      if (errorSent) { await send("✅ Связь с Playtomic восстановлена, продолжаю следить."); errorSent = false; }
      show(`Последняя проверка: ${local(new Date()).hm}<br>Подходящих свободных слотов: ${Object.keys(cur).length}`);
    } catch (e) {
      show(`⚠️ Ошибка: ${e.message}<br>Попробую снова через ${EVERY_SEC} с`);
      if (!errorSent && !String(e.message).startsWith("Telegram")) { await send(`⚠️ Бот во вкладке не может получить данные: <code>${e.message}</code>`); errorSent = true; }
    }
  }

  window.__padelBot = setInterval(tick, EVERY_SEC * 1000);
  stop.onclick = () => { clearInterval(window.__padelBot); window.__padelBot = null; box.remove(); };
  show("Первая проверка…");
  tick();
})();
