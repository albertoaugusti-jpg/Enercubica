/* Enercubica — comportamenti del sito */

(function () {
  // Menu mobile
  var bottone = document.querySelector('.nav-hamburger');
  var menu = document.getElementById('menu');
  if (bottone && menu) {
    bottone.addEventListener('click', function () {
      var aperto = menu.classList.toggle('aperto');
      bottone.setAttribute('aria-expanded', aperto ? 'true' : 'false');
      bottone.setAttribute('aria-label', aperto ? 'Chiudi il menu' : 'Apri il menu');
    });
  }

  // Modulo contatti
  var modulo = document.getElementById('modulo-contatto');
  if (!modulo) return;

  var esito = document.getElementById('esito-modulo');
  var invio = modulo.querySelector('button[type=submit]');
  var testoInvio = invio ? invio.textContent : '';

  modulo.addEventListener('submit', function (e) {
    e.preventDefault();
    esito.className = 'esito';
    esito.textContent = '';

    var dati = {};
    new FormData(modulo).forEach(function (v, k) { dati[k] = v; });
    dati.origine = window.location.pathname;

    if (!dati.nome || !dati.email) {
      esito.className = 'esito ko';
      esito.textContent = 'Servono almeno il nome e un indirizzo email.';
      return;
    }

    invio.disabled = true;
    invio.textContent = 'Invio in corso…';

    fetch('/api/contatto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dati)
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          modulo.reset();
          esito.className = 'esito ok';
          esito.textContent = 'Richiesta inviata. Ti ricontattiamo al più presto.';
        } else {
          esito.className = 'esito ko';
          esito.textContent = d.errore || 'Invio non riuscito. Riprova.';
        }
      })
      .catch(function () {
        esito.className = 'esito ko';
        esito.textContent = 'Invio non riuscito. Scrivici a ' +
          'a.valzania@enercubica.it oppure chiama lo 010 6201555.';
      })
      .finally(function () {
        invio.disabled = false;
        invio.textContent = testoInvio;
      });
  });
})();
