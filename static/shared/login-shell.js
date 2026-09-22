(() => {
  const stage = document.querySelector('[data-login-variant] .login-stage');
  const panel = stage?.querySelector('.login-panel');
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  if (stage && panel && !reduceMotion) {
    stage.addEventListener('pointermove', (event) => {
      const bounds = panel.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / Math.max(bounds.width, 1) - 0.5;
      const y = (event.clientY - bounds.top) / Math.max(bounds.height, 1) - 0.5;
      panel.style.setProperty('--login-ry', `${(x * 2.4).toFixed(2)}deg`);
      panel.style.setProperty('--login-rx', `${(-y * 2).toFixed(2)}deg`);
    });

    stage.addEventListener('pointerleave', () => {
      panel.style.setProperty('--login-ry', '0deg');
      panel.style.setProperty('--login-rx', '0deg');
    });
  }

  document.querySelectorAll('[data-action="toggle-password"]').forEach((button) => {
    button.addEventListener('click', () => {
      const targetId = button.getAttribute('aria-controls');
      const input = targetId ? document.getElementById(targetId) : null;
      if (!(input instanceof HTMLInputElement)) return;
      const visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      button.setAttribute('aria-label', visible ? '显示密码' : '隐藏密码');
      button.setAttribute('aria-pressed', String(!visible));
      button.dataset.visible = visible ? 'false' : 'true';
    });
  });
})();
