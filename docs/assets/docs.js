/* ============================================================
   Nawigacja dokumentacji: Wirtualny Pracownik AI.

   JEDNO zrodlo listy sekcji. Powloka (index.html) renderuje z niego
   lewe menu, laduje pliki z sekcje/ do ramki, obsluguje zwijanie grup,
   filtr i linki bezposrednie (#id w adresie).

   Chcesz dodac sekcje? Dwa kroki: plik w sekcje/<id>.html + jeden
   wpis nizej. Nic wiecej. Opisane w sekcji "Jak edytowac".
   ============================================================ */

var SECTIONS = [
  { grupa: "Przegląd", items: [
    { id: "00-start", ikona: "🏠", label: "Start" }
  ] },
  { grupa: "Jak to działa", items: [
    { id: "01-co-to-jest",      ikona: "💡", label: "Czym jest wirtualny pracownik" },
    { id: "02-droga-zadania",   ikona: "🔀", label: "Droga zadania" },
    { id: "03-architektura",    ikona: "🧱", label: "Jak to jest zbudowane" },
    { id: "04-kontrola-jakosci",ikona: "✅", label: "Kontrola jakości" },
    { id: "05-zespol-botow",    ikona: "👥", label: "Zespół botów" }
  ] },
  { grupa: "Praca na co dzień", items: [
    { id: "06-skad-zadania",    ikona: "📥", label: "Skąd biorą się zadania" },
    { id: "07-wiedza-o-firmie", ikona: "🏢", label: "Wiedza o firmie" },
    { id: "08-sterowanie",      ikona: "🎛️", label: "Sterowanie i nadzór" }
  ] },
  { grupa: "Ramy", items: [
    { id: "09-bezpieczenstwo",  ikona: "🛡️", label: "Bezpieczeństwo i granice" },
    { id: "10-koszty",          ikona: "💰", label: "Modele i koszty" }
  ] },
  { grupa: "Wdrożenie", items: [
    { id: "11-instalacja",      ikona: "⚙️", label: "Instalacja maszyny" },
    { id: "12-mapa-repozytorium", ikona: "🗂️", label: "Mapa repozytorium" }
  ] },
  { grupa: "Stan projektu", items: [
    { id: "13-co-dziala",       ikona: "📈", label: "Co już działa" },
    { id: "14-co-dalej",        ikona: "🧭", label: "Co dalej" },
    { id: "15-jak-edytowac",    ikona: "✏️", label: "Jak edytować tę dokumentację" }
  ] }
];

/* Mapa id -> etykieta, do okruszka i podswietlenia pozycji. */
var LABELS = {};
SECTIONS.forEach(function (g) { g.items.forEach(function (it) { LABELS[it.id] = it.label; }); });

function renderNav() {
  var html = "";
  SECTIONS.forEach(function (g, gi) {
    html += '<div class="nav-group" data-g="' + gi + '">';
    html += '<div class="nav-group-label" onclick="toggleGrupa(' + gi + ')">' +
            g.grupa + '<span class="chev">&#9660;</span></div>';
    html += '<div class="nav-list">';
    g.items.forEach(function (it) {
      html += '<div class="nav-item" data-id="' + it.id + '" tabindex="0" role="link"' +
              ' onclick="docNav(\'' + it.id + '\')"' +
              ' onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();docNav(\'' + it.id + '\')}">' +
              '<span class="ico">' + it.ikona + '</span><span class="lab">' + it.label + '</span></div>';
    });
    html += '</div></div>';
  });
  document.getElementById("nav").innerHTML = html;
}

function toggleGrupa(gi) {
  var g = document.querySelector('.nav-group[data-g="' + gi + '"]');
  if (g) g.classList.toggle("collapsed");
}

/* Zaladowanie sekcji do ramki. Wywolywane z menu ORAZ z linkow wewnatrz
   sekcji: <a href="02-droga-zadania.html"
              onclick="if(parent!==window){parent.docNav('02-droga-zadania');return false}">
   Dzieki temu sekcja otwarta osobno (dwuklik w pliku) tez dziala. */
function docNav(id) {
  if (!LABELS[id]) return;
  document.getElementById("view").src = "sekcje/" + id + ".html";
  document.getElementById("crumb").innerHTML = 'Dokumentacja &middot; <b>' + LABELS[id] + "</b>";
  document.querySelectorAll(".nav-item").forEach(function (el) {
    el.classList.toggle("active", el.getAttribute("data-id") === id);
  });
  var el = document.querySelector('.nav-item[data-id="' + id + '"]');
  if (el) {
    var grp = el.closest(".nav-group");
    if (grp) grp.classList.remove("collapsed");
  }
  if (location.hash.replace("#", "") !== id) {
    history.replaceState(null, "", "#" + id);
  }
}

function filtrujNav() {
  var q = document.getElementById("navSearch").value.toLowerCase().trim();
  SECTIONS.forEach(function (g, gi) {
    var grp = document.querySelector('.nav-group[data-g="' + gi + '"]');
    var widoczne = 0;
    grp.querySelectorAll(".nav-item").forEach(function (el) {
      var pasuje = !q || el.querySelector(".lab").textContent.toLowerCase().indexOf(q) >= 0;
      el.style.display = pasuje ? "" : "none";
      if (pasuje) widoczne++;
    });
    grp.style.display = widoczne ? "" : "none";
    if (q) grp.classList.remove("collapsed");
  });
}

document.addEventListener("DOMContentLoaded", function () {
  renderNav();
  document.getElementById("navSearch").addEventListener("input", filtrujNav);
  var start = location.hash.replace("#", "");
  docNav(LABELS[start] ? start : "00-start");
});
