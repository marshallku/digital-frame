// Ultralight digital frame — slideshow controller.
// Two stacked layers crossfade; the next image is preloaded before every swap.

const stage = document.getElementById("stage");
const layers = [...document.querySelectorAll(".layer")];
const clockEl = document.getElementById("clock");
const progressEl = document.querySelector("#progress > span");
const messageEl = document.getElementById("message");
const hintEl = document.getElementById("hint");

const state = {
    interval: 8000,
    transition: 1500,
    kenburns: true,
    count: 0,
    order: [],
    cursor: -1,
    active: 0, // index into `layers`
    paused: false,
    timerStart: 0,
    remaining: 0,
    tickHandle: 0,
};

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

async function boot() {
    let config;
    try {
        config = await fetch("/api/config").then((r) => r.json());
    } catch {
        showMessage("서버에 연결할 수 없습니다.");
        return;
    }

    state.interval = Math.max(1, config.interval) * 1000;
    state.transition = clamp(config.transition * 1000, 0, state.interval - 100);
    state.kenburns = Boolean(config.kenburns);
    state.count = config.count;

    document.documentElement.style.setProperty("--transition", `${state.transition}ms`);
    document.documentElement.style.setProperty("--kenburns-duration", `${state.interval + state.transition}ms`);

    if (!state.count) {
        showMessage("표시할 이미지가 없습니다.<br />대상 폴더에 이미지를 넣어주세요.");
        return;
    }

    state.order = shuffleView(state.count);
    startClock();
    bindControls();
    bindIdleWatcher();
    hintEl.style.opacity = "1";
    setTimeout(() => hintEl.classList.add("fade-out"), 6000);
    advance(1, true);
}

// A stable [0..n) list; the server already applied --shuffle, so keep order here.
function shuffleView(n) {
    return Array.from({ length: n }, (_, i) => i);
}

function imageUrl(imageIndex) {
    return `/img/${imageIndex}`;
}

function preload(imageIndex) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.decoding = "async";
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error(`failed: ${imageIndex}`));
        img.src = imageUrl(imageIndex);
    });
}

async function advance(direction, immediate = false, attempts = 0) {
    if (attempts >= state.count) {
        showMessage("표시할 수 있는 이미지가 없습니다.");
        return;
    }

    const nextCursor = (state.cursor + direction + state.count) % state.count;
    const imageIndex = state.order[nextCursor];

    let loaded;
    try {
        loaded = await preload(imageIndex);
    } catch {
        // Skip a broken file; after `count` consecutive failures give up instead of looping.
        state.cursor = nextCursor;
        advance(direction > 0 ? 1 : -1, immediate, attempts + 1);
        return;
    }

    state.cursor = nextCursor;
    swapTo(loaded.src, immediate);
    restartTimer();
}

function swapTo(src, immediate) {
    const nextSlot = state.active ^ 1;
    const layer = layers[nextSlot];
    const prev = layers[state.active];

    layer.innerHTML = "";
    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    backdrop.style.backgroundImage = `url("${src}")`;
    const photo = document.createElement("img");
    photo.className = "photo";
    photo.src = src;
    photo.alt = "";
    layer.append(backdrop, photo);

    layer.classList.remove("kenburns");
    if (state.kenburns) {
        const sign = () => (Math.random() < 0.5 ? -1 : 1);
        layer.style.setProperty("--kb-x", `${(1 + Math.random()) * sign()}%`);
        layer.style.setProperty("--kb-y", `${(1 + Math.random()) * sign()}%`);
        void layer.offsetWidth; // force reflow so the animation restarts
        layer.classList.add("kenburns");
    }

    if (immediate) {
        layer.style.transition = "none";
        layer.classList.add("active");
        void layer.offsetWidth;
        layer.style.transition = "";
    } else {
        layer.classList.add("active");
    }
    prev.classList.remove("active");
    state.active = nextSlot;
}

// -- timing ---------------------------------------------------------------

function restartTimer() {
    state.remaining = state.interval;
    state.timerStart = performance.now();
    if (!state.paused) {
        tick();
    }
}

function tick() {
    cancelAnimationFrame(state.tickHandle);
    const loop = (now) => {
        if (state.paused) return;
        const elapsed = now - state.timerStart;
        const ratio = clamp(elapsed / state.interval, 0, 1);
        progressEl.style.width = `${ratio * 100}%`;
        if (elapsed >= state.remaining) {
            advance(1);
            return;
        }
        state.tickHandle = requestAnimationFrame(loop);
    };
    state.tickHandle = requestAnimationFrame(loop);
}

function togglePause() {
    state.paused = !state.paused;
    document.body.classList.toggle("paused", state.paused);
    if (state.paused) {
        cancelAnimationFrame(state.tickHandle);
        state.remaining -= performance.now() - state.timerStart;
    } else {
        state.timerStart = performance.now();
        tick();
    }
}

// -- controls -------------------------------------------------------------

function bindControls() {
    window.addEventListener("keydown", (event) => {
        switch (event.key) {
            case " ":
                event.preventDefault();
                togglePause();
                break;
            case "ArrowRight":
                manualAdvance(1);
                break;
            case "ArrowLeft":
                manualAdvance(-1);
                break;
            case "f":
            case "F":
                toggleFullscreen();
                break;
            default:
                break;
        }
    });

    let lastTap = 0;
    stage.addEventListener("click", (event) => {
        const now = performance.now();
        if (now - lastTap < 300) {
            toggleFullscreen();
        } else {
            // Left third = previous, right two-thirds = next.
            manualAdvance(event.clientX < window.innerWidth / 3 ? -1 : 1);
        }
        lastTap = now;
    });
}

function manualAdvance(direction) {
    cancelAnimationFrame(state.tickHandle);
    advance(direction);
}

function toggleFullscreen() {
    if (document.fullscreenElement) {
        document.exitFullscreen?.();
    } else {
        document.documentElement.requestFullscreen?.().catch(() => {});
    }
}

function bindIdleWatcher() {
    let idleTimer = 0;
    const wake = () => {
        document.body.classList.remove("idle");
        clearTimeout(idleTimer);
        idleTimer = setTimeout(() => document.body.classList.add("idle"), 3500);
    };
    ["mousemove", "keydown", "click", "touchstart"].forEach((type) =>
        window.addEventListener(type, wake, { passive: true }),
    );
    wake();
}

// -- overlays -------------------------------------------------------------

function startClock() {
    const render = () => {
        const now = new Date();
        const hh = String(now.getHours()).padStart(2, "0");
        const mm = String(now.getMinutes()).padStart(2, "0");
        clockEl.textContent = `${hh}:${mm}`;
    };
    render();
    setInterval(render, 10000);
}

function showMessage(html) {
    messageEl.innerHTML = html;
    messageEl.hidden = false;
}

boot();
