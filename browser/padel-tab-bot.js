(async () => {
  // 🎾 Padel-Bot im Browser-Tab: Mitte Cabrio → Telegram (nur Double Courts).
  // Läuft, solange der Playtomic-Tab offen ist. Prüft alle 90 Sekunden.
  const TENANT = "24234663-6264-471c-91fe-20fa80cf52d5";
  const CLUB_URL = "https://playtomic.com/clubs/mitte-the-cabrio";
  const CHAT_ID = "-5365069771";
  const EVERY_SEC = 90, DAYS_AHEAD = 13, WEEKDAY_FROM = 17 * 60 + 30, MAX_MSGS = 10;
  const DURATIONS = [60, 90, 120];
  const COURTS = {
    "791eebbc-8619-42da-9aa8-d82623aac207": "Court 1 · 1. OG",
    "bbe38091-21ad-4232-8569-db2144db27f9": "Court 2 · 1. OG",
    "abbc9711-39e0-4460-914b-ca57efaa46c1": "Court 3 · 1. OG",
    "723feed7-a142-440e-8b97-e639d39bd4f4": "Court 4 · 1. OG",
    "0b80603b-be4a-414d-bb21-0f12c246ddec": "Court 6 · 5. OG",
    "5ce3f40c-99bd-48a6-9117-460b4e133893": "Court 7 · 5. OG",
    "8283064b-4552-406a-9970-b305717b26c5": "Court 8 · 5. OG",
    "b1556e5b-d4f1-4335-98df-299c8fc86c6c": "Court 9 · 5. OG"
  };
  const SINGLE = ["d2731550-e8ad-4d09-8ab4-0bb633c80b50", "759403bb-5f15-40f9-aca4-445ae55ea0f3", "0b972e5b-874e-4be2-98a5-3260d0433d16"];
  const WD = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
  const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };

  if (!location.hostname.endsWith("playtomic.com")) {
    if (confirm("Der Bot läuft nur auf der Playtomic-Seite. Clubseite öffnen? Danach das Lesezeichen erneut klicken.")) location.href = CLUB_URL;
    return;
  }
  if (window.__padelBot) { alert("🎾 Der Bot läuft in diesem Tab bereits."); return; }

  let token = LS("padelBotToken");
  if (!token) {
    token = (prompt("Erster Start: Bot-Token von @BotFather einfügen:") || "").replace(/\s+/g, "");
    if (!token) return;
    const me = await fetch(`https://api.telegram.org/bot${token}/getMe`).then(r => r.json()).catch(() => ({}));
    if (!me.ok) { alert("❌ Telegram hat den Token nicht akzeptiert. Bitte prüfen und erneut klicken."); return; }
    LS("padelBotToken", token);
  }

  const box = document.createElement("div");
  box.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;background:#111;color:#fff;font:13px/1.4 -apple-system,sans-serif;padding:10px 14px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.3);max-width:280px";
  const status = document.createElement("div");
  const stop = document.createElement("button");
  stop.textContent = "Stoppen";
  stop.style.cssText = "margin-top:6px;background:#333;color:#fff;border:0;border-radius:6px;padding:3px 8px;cursor:pointer";
  box.append(status, stop);
  document.body.appendChild(box);
  const show = t => { status.innerHTML = "🎾 <b>Padel-Bot läuft</b><br>" + t + "<br><small>Diesen Tab nicht schließen</small>"; };

  const send = (text, buttons) => {
    const body = new URLSearchParams({ chat_id: CHAT_ID, text, parse_mode: "HTML", disable_web_page_preview: "true" });
    if (buttons) body.set("reply_markup", JSON.stringify({ inline_keyboard: buttons }));
    return fetch(`https://api.telegram.org/bot${token}/sendMessage`, { method: "POST", body })
      .then(r => r.json()).catch(e => ({ ok: false, description: String(e) }));
  };

  const berlin = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short" });
  const parts = d => Object.fromEntries(berlin.formatToParts(d).map(p => [p.type, p.value]));
  const local = d => { const p = parts(d); return { date: `${p.year}-${p.month}-${p.day}`, hm: `${p.hour}:${p.minute}`, min: +p.hour * 60 + +p.minute, wd: ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].indexOf(p.weekday) }; };
  const bookUrl = (rid, iso, dur) => "https://app.playtomic.com/payments?" + new URLSearchParams({
    type: "CUSTOMER_MATCH", tenant_id: TENANT, resource_id: rid, start: iso, duration: String(dur), sport_id: "PADEL" });
  const dayLabel = s => { const [, m, d] = s.date.split("-"); return `${WD[s.wd]} ${d}.${m}.`; };

  async function collect() {
    const now = new Date(), found = {};
    let ok = 0, lastErr = "", lastDay = "";
    for (let i = 0; i <= DAYS_AHEAD; i++) {
      const day = local(new Date(now.getTime() + i * 864e5)).date;
      try {
        const r = await fetch(`/api/clubs/availability?tenant_id=${TENANT}&date=${day}&sport_id=PADEL`, { headers: { Accept: "application/json" } });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json(); ok++; lastDay = day;
        for (const b of data || []) {
          if (SINGLE.includes(b.resource_id)) continue;
          for (const s of b.slots || []) {
            const t = new Date(`${b.start_date}T${s.start_time}Z`);
            if (t <= now || !DURATIONS.includes(s.duration)) continue;
            const L = local(t);
            if (L.date !== day) continue;
            const weekend = L.wd === 0 || L.wd === 6;
            if (!weekend && L.min < WEEKDAY_FROM) continue;
            found[`${b.resource_id}|${L.date}T${L.hm}|${s.duration}`] = {
              rid: b.resource_id, court: COURTS[b.resource_id] || "Double Court",
              date: L.date, wd: L.wd, hm: L.hm, dur: s.duration, price: s.price, iso: t.toISOString() };
          }
        }
      } catch (e) { lastErr = e.message; }
      await new Promise(r => setTimeout(r, 400));
    }
    if (!ok) throw new Error("Playtomic antwortet nicht: " + lastErr);
    return { found, lastDay };
  }

  // Ein Court + Startzeit = eine Nachricht, mit einem Buchen-Button pro Dauer.
  function group(list) {
    const g = {};
    list.forEach(s => { (g[`${s.rid}|${s.date}T${s.hm}`] ||= []).push(s); });
    return Object.values(g)
      .map(a => a.sort((x, y) => x.dur - y.dur))
      .sort((a, b) => (a[0].date + a[0].hm + a[0].court).localeCompare(b[0].date + b[0].hm + b[0].court));
  }

  async function announce(slots) {
    const groups = group(slots);
    for (const a of groups.slice(0, MAX_MSGS)) {
      const s = a[0];
      const text = `🎾 <b>Platz frei!</b>\n📅 <b>${dayLabel(s)} · ${s.hm} Uhr</b>\n📍 ${s.court}\n` +
        a.map(x => `⏱ ${x.dur} Min · ${x.price.replace(" EUR", " €")}`).join("\n");
      const buttons = [a.map(x => ({ text: `Buchen ${x.dur} Min`, url: bookUrl(x.rid, x.iso, x.dur) }))];
      const r = await send(text, buttons);
      if (!r.ok) throw new Error("Telegram: " + r.description);
      await new Promise(r => setTimeout(r, 1200));
    }
    if (groups.length > MAX_MSGS) {
      await send(`➕ Und ${groups.length - MAX_MSGS} weitere freie Slots – alle auf <a href="${CLUB_URL}">Playtomic</a>.`);
    }
  }

  async function summary(slots) {
    const lines = group(slots).map(a => {
      const s = a[0];
      return `• ${dayLabel(s)} ${s.hm} · ${s.court} · ` +
        a.map(x => `<a href="${bookUrl(x.rid, x.iso, x.dur)}">${x.dur} Min</a>`).join(" / ");
    });
    let text = `🎾 <b>Mitte Cabrio</b>: Bot gestartet.\nAktuell frei: ${lines.length} Slots auf Double Courts (Mo–Fr ab 17:30, Sa–So ganztägig). Auf die Dauer tippen zum Buchen:\n\n` + lines.join("\n") +
      `\n\nAb jetzt melde ich nur neu frei gewordene Plätze.`;
    while (text.length > 3800) {
      const cut = text.lastIndexOf("\n•", 3800);
      await send(text.slice(0, cut)); text = text.slice(cut);
    }
    const r = await send(text);
    if (!r.ok) throw new Error("Telegram: " + r.description);
  }

  let errorSent = false;
  async function tick() {
    try {
      const { found: cur, lastDay } = await collect();
      const prevRaw = LS("padelBotSeen2");
      const prev = prevRaw ? JSON.parse(prevRaw) : null;
      const prevLastDay = LS("padelBotLastDay") || "";
      if (!prev) {
        await summary(Object.values(cur));
      } else {
        // Neue Tage, die gerade erst ins Buchungsfenster rutschen, nicht melden.
        const fresh = Object.keys(cur).filter(k => !(k in prev) && (!prevLastDay || cur[k].date <= prevLastDay));
        if (fresh.length) await announce(fresh.map(k => cur[k]));
      }
      LS("padelBotSeen2", JSON.stringify(cur));
      if (lastDay) LS("padelBotLastDay", lastDay);
      if (errorSent) { await send("✅ Verbindung zu Playtomic wieder da, ich beobachte weiter."); errorSent = false; }
      show(`Letzte Prüfung: ${local(new Date()).hm}<br>Freie Slots (Double): ${Object.keys(cur).length}`);
    } catch (e) {
      show(`⚠️ Fehler: ${e.message}<br>Neuer Versuch in ${EVERY_SEC} s`);
      if (!errorSent && !String(e.message).startsWith("Telegram")) { await send(`⚠️ Der Bot bekommt keine Daten von Playtomic: <code>${e.message}</code>`); errorSent = true; }
    }
  }

  window.__padelBot = setInterval(tick, EVERY_SEC * 1000);
  stop.onclick = () => { clearInterval(window.__padelBot); window.__padelBot = null; box.remove(); };
  show("Erste Prüfung…");
  tick();
})();
