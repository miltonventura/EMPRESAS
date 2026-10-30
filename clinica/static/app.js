// Comportamientos pequeños de los formularios (la aplicación funciona sin JavaScript).
document.addEventListener('DOMContentLoaded', function () {
  // Muestra u oculta bloques según una casilla o un valor de lista:
  //   data-mostrar-si="id_del_control"            -> visible si la casilla está marcada
  //   data-mostrar-si="id_del_control=valor"      -> visible si el control tiene ese valor
  //   data-mostrar-si="!id_del_control"           -> visible si el control está vacío / desmarcado
  document.querySelectorAll('[data-mostrar-si]').forEach(function (bloque) {
    var regla = bloque.dataset.mostrarSi;
    var negado = regla.charAt(0) === '!';
    if (negado) regla = regla.slice(1);
    var partes = regla.split('=');
    var control = document.getElementById(partes[0]);
    if (!control) return;
    function actualizar() {
      var activo;
      if (partes.length > 1) activo = control.value === partes[1];
      else if (control.type === 'checkbox') activo = control.checked;
      else activo = control.value.trim() !== '';
      if (negado) activo = !activo;
      bloque.classList.toggle('oculto', !activo);
    }
    control.addEventListener('change', actualizar);
    control.addEventListener('input', actualizar);
    actualizar();
  });

  // Filtra la lista de médicos según la especialidad elegida.
  var especialidad = document.getElementById('especialidad');
  var medico = document.getElementById('medico_id');
  if (especialidad && medico) {
    function filtrarMedicos() {
      Array.prototype.forEach.call(medico.options, function (op) {
        if (!op.value) return;
        var visible = !especialidad.value || op.dataset.especialidad === especialidad.value;
        op.hidden = !visible;
        if (!visible && op.selected) medico.value = '';
      });
    }
    especialidad.addEventListener('change', filtrarMedicos);
    filtrarMedicos();
  }

  // Botones "Copiar" junto a enlaces.
  document.querySelectorAll('[data-copiar]').forEach(function (boton) {
    boton.addEventListener('click', function () {
      var campo = document.getElementById(boton.dataset.copiar);
      campo.select();
      if (navigator.clipboard) navigator.clipboard.writeText(campo.value);
      else document.execCommand('copy');
      boton.textContent = 'Copiado';
      setTimeout(function () { boton.textContent = 'Copiar'; }, 1500);
    });
  });

  // Confirmación antes de acciones irreversibles.
  document.querySelectorAll('form[data-confirmar]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!confirm(form.dataset.confirmar)) e.preventDefault();
    });
  });
});
