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
    random: true,
    count: 0,
    order: [],
    trail: [], // image indices already shown, for back-navigation
    trailPos: -1, // where we currently are within `trail`
    active: 0, // index into `layers`
    paused: false,
    timerStart: 0,
    remaining: 0,
    tickHandle: 0,
};

const TRAIL_LIMIT = 1000;

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
    state.random = config.random !== false;
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
    // Hint starts visible (stylesheet default); let it fade out on its own after a few seconds.
    // Avoid an inline opacity here — it would override the idle/fullscreen/fade-out CSS rules.
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

// The image shown after `anchor` when moving forward into new territory, never
// returning `avoid` (the currently-shown photo). `walk` forces the deterministic
// next-in-order pick, which the broken-image retry uses so every index is tried
// within `count` attempts (guaranteed skip, and it never wraps back onto `avoid`).
function freshIndex(anchor, walk, avoid) {
    if (state.count <= 1) {
        return state.order[0];
    }
    if (!state.random || walk) {
        let pos = anchor < 0 ? -1 : state.order.indexOf(anchor);
        let index;
        let steps = 0;
        do {
            pos = (pos + 1) % state.count;
            index = state.order[pos];
            steps += 1;
        } while (index === avoid && steps < state.count);
        return index;
    }
    let index;
    do {
        index = state.order[Math.floor(Math.random() * state.count)];
    } while (index === anchor || index === avoid); // never repeat the current photo
    return index;
}

async function advance(direction, immediate = false, attempts = 0, anchor, avoid) {
    if (attempts >= state.count) {
        showMessage("표시할 수 있는 이미지가 없습니다.");
        return;
    }

    // Replaying already-seen history (back, or forward after going back) vs. new territory.
    const replaying = direction > 0 ? state.trailPos < state.trail.length - 1 : state.trailPos > 0;
    if (direction < 0 && !replaying) {
        restartTimer(); // nothing before the first image — keep auto-advance alive
        return;
    }
    const current = state.trailPos >= 0 ? state.trail[state.trailPos] : -1;
    // On a retry `anchor` is the last (broken) candidate; `avoid` stays the photo on
    // screen so skipping broken files can never loop back onto it.
    const base = anchor === undefined ? current : anchor;
    const skip = avoid === undefined ? current : avoid;
    const imageIndex = replaying ? state.trail[state.trailPos + direction] : freshIndex(base, anchor !== undefined, skip);

    let loaded;
    try {
        loaded = await preload(imageIndex);
    } catch {
        // Skip a broken file; after `count` attempts give up instead of looping forever.
        if (replaying) {
            state.trailPos += direction; // step over the dead trail entry
            advance(direction, immediate, attempts + 1);
        } else {
            advance(direction, immediate, attempts + 1, imageIndex, skip); // walk on from the broken one
        }
        return;
    }

    if (replaying) {
        state.trailPos += direction;
    } else {
        state.trail.length = state.trailPos + 1; // drop any forward history we branched from
        state.trail.push(imageIndex);
        state.trailPos = state.trail.length - 1;
        if (state.trail.length > TRAIL_LIMIT) {
            state.trail.shift();
            state.trailPos -= 1;
        }
    }

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

    document.addEventListener("fullscreenchange", () => {
        document.body.classList.toggle("fullscreen", Boolean(document.fullscreenElement));
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
