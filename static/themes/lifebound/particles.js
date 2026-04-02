/**
 * particles-lifebound.js
 * ======================
 * Animación de pétalos cayendo para el tema Lifebound.
 * Se inyecta automáticamente cuando theme=lifebound.
 *
 * Cada tema puede tener su propio particles.js con lógica diferente.
 * Este archivo solo toca el <canvas id="particle-canvas"> y nada más.
 */

(function () {
  const canvas = document.getElementById("particle-canvas");
  if (!canvas) return;

  const ctx    = canvas.getContext("2d");
  const petals = [];
  const COUNT  = 28;

  // Paleta de pétalos
  const COLORS = [
    "rgba(255, 192, 180, 0.7)",
    "rgba(255, 210, 200, 0.6)",
    "rgba(255, 230, 220, 0.5)",
    "rgba(240, 180, 195, 0.65)",
    "rgba(220, 200, 210, 0.55)",
  ];

  function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
  }

  function randomBetween(a, b) {
    return a + Math.random() * (b - a);
  }

  function createPetal(fromTop = false) {
    return {
      x:        randomBetween(0, canvas.width),
      y:        fromTop ? randomBetween(-60, 0) : randomBetween(-60, canvas.height),
      size:     randomBetween(6, 14),
      speedY:   randomBetween(0.6, 1.8),
      speedX:   randomBetween(-0.4, 0.4),
      rotation: randomBetween(0, Math.PI * 2),
      rotSpeed: randomBetween(-0.015, 0.015),
      opacity:  randomBetween(0.4, 0.85),
      color:    COLORS[Math.floor(Math.random() * COLORS.length)],
      wobble:   randomBetween(0, Math.PI * 2),
      wobbleSpeed: randomBetween(0.01, 0.025),
    };
  }

  function drawPetal(p) {
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.rotation);
    ctx.globalAlpha = p.opacity;
    ctx.fillStyle   = p.color;

    // Forma de pétalo (elipse ligeramente alargada con punta)
    ctx.beginPath();
    ctx.ellipse(0, 0, p.size * 0.45, p.size, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }

  function update(p) {
    p.wobble    += p.wobbleSpeed;
    p.x         += p.speedX + Math.sin(p.wobble) * 0.35;
    p.y         += p.speedY;
    p.rotation  += p.rotSpeed;

    // Regresar al tope si salió por abajo
    if (p.y > canvas.height + 30) {
      Object.assign(p, createPetal(true));
    }
  }

  function loop() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    petals.forEach(p => {
      update(p);
      drawPetal(p);
    });
    requestAnimationFrame(loop);
  }

  // Inicializar
  resize();
  window.addEventListener("resize", resize);

  for (let i = 0; i < COUNT; i++) {
    petals.push(createPetal(false));
  }

  // Respeto a prefers-reduced-motion
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  loop();
})();
