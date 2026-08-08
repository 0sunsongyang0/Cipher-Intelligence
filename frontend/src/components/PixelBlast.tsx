import { useEffect, useRef, type CSSProperties } from "react";
import { Mesh, Program, Renderer, Triangle } from "ogl";
import "./PixelBlast.css";

export type PixelBlastVariant = "square" | "circle" | "triangle" | "diamond";

type PixelBlastProps = {
  variant?: PixelBlastVariant;
  pixelSize?: number;
  color?: string;
  patternScale?: number;
  patternDensity?: number;
  pixelSizeJitter?: number;
  enableRipples?: boolean;
  rippleSpeed?: number;
  rippleThickness?: number;
  rippleIntensityScale?: number;
  liquid?: boolean;
  liquidStrength?: number;
  liquidRadius?: number;
  liquidWobbleSpeed?: number;
  speed?: number;
  edgeFade?: number;
  transparent?: boolean;
  className?: string;
  style?: CSSProperties;
};

const shapeMap: Record<PixelBlastVariant, number> = {
  square: 0,
  circle: 1,
  triangle: 2,
  diamond: 3,
};

function hexToRgb(hex: string): [number, number, number] {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!match) return [1, 1, 1];
  return [
    Number.parseInt(match[1], 16) / 255,
    Number.parseInt(match[2], 16) / 255,
    Number.parseInt(match[3], 16) / 255,
  ];
}

const vertex = `#version 300 es
in vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const fragment = `#version 300 es
precision highp float;

uniform vec2 uResolution;
uniform float uTime;
uniform vec3 uColor;
uniform float uPixelSize;
uniform float uScale;
uniform float uDensity;
uniform float uPixelJitter;
uniform float uShapeType;
uniform float uEnableRipples;
uniform vec2 uClickPos;
uniform float uClickTime;
uniform float uRippleSpeed;
uniform float uRippleThickness;
uniform float uRippleIntensity;
uniform float uEdgeFade;
uniform float uLiquid;
uniform vec2 uPointer;
uniform float uLiquidStrength;
uniform float uLiquidRadius;
uniform float uLiquidWobble;
out vec4 fragColor;

float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float valueNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash21(i), hash21(i + vec2(1.0, 0.0)), f.x),
             mix(hash21(i + vec2(0.0, 1.0)), hash21(i + 1.0), f.x), f.y);
}

float fbm(vec2 p) {
  float value = 0.0;
  float amplitude = 0.55;
  for (int index = 0; index < 5; index++) {
    value += amplitude * valueNoise(p);
    p = p * 1.85 + 17.4;
    amplitude *= 0.52;
  }
  return value;
}

float bayer4(vec2 position) {
  vec2 p = mod(floor(position), 4.0);
  float x = p.x;
  float y = p.y;
  return fract((x * 0.5 + y * y * 0.75) * 0.25 + (x + y * 2.0) * 0.0625);
}

float circleMask(vec2 p, float coverage) {
  float radius = sqrt(max(coverage, 0.0)) * 0.48;
  float distanceToEdge = length(p - 0.5) - radius;
  return 1.0 - smoothstep(-fwidth(distanceToEdge), fwidth(distanceToEdge), distanceToEdge);
}

float triangleMask(vec2 p, vec2 id, float coverage) {
  if (mod(id.x + id.y, 2.0) > 0.5) p.x = 1.0 - p.x;
  float edge = p.y - sqrt(max(coverage, 0.0)) * (1.0 - p.x);
  return clamp(0.5 - edge / max(fwidth(edge), 0.001), 0.0, 1.0);
}

float diamondMask(vec2 p, float coverage) {
  float radius = sqrt(max(coverage, 0.0)) * 0.7;
  return 1.0 - smoothstep(radius, radius + 0.035, abs(p.x - 0.5) + abs(p.y - 0.5));
}

void main() {
  vec2 normalized = gl_FragCoord.xy / uResolution;
  vec2 liquidOffset = vec2(0.0);
  if (uLiquid > 0.5) {
    float pointerDistance = distance(normalized, uPointer);
    float pointerFalloff = smoothstep(uLiquidRadius, 0.0, pointerDistance);
    float wobble = sin(uTime * uLiquidWobble + pointerDistance * 30.0);
    liquidOffset = normalize(normalized - uPointer + vec2(0.0001)) * pointerFalloff * wobble * uLiquidStrength;
  }

  vec2 fragCoord = gl_FragCoord.xy + liquidOffset * uResolution;
  vec2 centered = fragCoord - uResolution * 0.5;
  vec2 pixelId = floor(centered / uPixelSize);
  vec2 pixelUv = fract(centered / uPixelSize);
  float aspect = uResolution.x / max(uResolution.y, 1.0);
  vec2 patternUv = centered / uResolution.y;
  patternUv.x *= aspect;

  float pattern = fbm(patternUv * uScale + vec2(uTime * 0.035, -uTime * 0.025));
  float feed = pattern - 0.58 + (uDensity - 1.0) * 0.24;

  if (uEnableRipples > 0.5 && uClickTime >= 0.0) {
    float elapsed = max(uTime - uClickTime, 0.0);
    float radius = elapsed * uRippleSpeed;
    float distanceFromClick = distance(normalized, uClickPos);
    float ring = exp(-pow((distanceFromClick - radius) / max(uRippleThickness, 0.001), 2.0));
    float attenuation = exp(-elapsed * 0.75) * exp(-distanceFromClick * 2.5);
    feed = max(feed, ring * attenuation * uRippleIntensity);
  }

  float dither = bayer4(fragCoord / uPixelSize) - 0.5;
  float activity = smoothstep(0.28, 0.62, feed + dither);
  float jitter = 1.0 + (hash21(pixelId) - 0.5) * uPixelJitter;
  float coverage = clamp(mix(0.16, 1.0, activity) * jitter, 0.12, 1.0);
  float intensity = mix(0.28, 1.0, activity);

  float mask = coverage;
  if (uShapeType > 0.5 && uShapeType < 1.5) mask = circleMask(pixelUv, coverage);
  else if (uShapeType > 1.5 && uShapeType < 2.5) mask = triangleMask(pixelUv, pixelId, coverage);
  else if (uShapeType > 2.5) mask = diamondMask(pixelUv, coverage);

  if (uEdgeFade > 0.0) {
    float edge = min(min(normalized.x, normalized.y), min(1.0 - normalized.x, 1.0 - normalized.y));
    mask *= smoothstep(0.0, uEdgeFade, edge);
  }

  mask *= intensity;
  fragColor = vec4(uColor * mask, mask);
}
`;

export function PixelBlast({
  variant = "circle",
  pixelSize = 6,
  color = "#B497CF",
  patternScale = 3,
  patternDensity = 1.2,
  pixelSizeJitter = 0.5,
  enableRipples = true,
  rippleSpeed = 0.4,
  rippleThickness = 0.12,
  rippleIntensityScale = 1.5,
  liquid = true,
  liquidStrength = 0.018,
  liquidRadius = 0.24,
  liquidWobbleSpeed = 5,
  speed = 0.6,
  edgeFade = 0,
  transparent = true,
  className = "",
  style,
}: PixelBlastProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || import.meta.env.MODE === "test") return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let renderer: Renderer;
    try {
      renderer = new Renderer({
        webgl: 2,
        alpha: transparent,
        premultipliedAlpha: true,
        antialias: false,
        dpr: Math.min(window.devicePixelRatio || 1, 1.35),
      });
    } catch {
      container.dataset.rendering = "fallback";
      return;
    }

    const gl = renderer.gl;
    gl.clearColor(0, 0, 0, transparent ? 0 : 1);
    const canvas = gl.canvas;
    canvas.setAttribute("aria-hidden", "true");
    container.appendChild(canvas);

    const program = new Program(gl, {
      vertex,
      fragment,
      transparent: true,
      uniforms: {
        uResolution: { value: new Float32Array([1, 1]) },
        uTime: { value: 0 },
        uColor: { value: new Float32Array(hexToRgb(color)) },
        uPixelSize: { value: pixelSize },
        uScale: { value: patternScale },
        uDensity: { value: patternDensity },
        uPixelJitter: { value: pixelSizeJitter },
        uShapeType: { value: shapeMap[variant] },
        uEnableRipples: { value: enableRipples && !reduceMotion.matches ? 1 : 0 },
        uClickPos: { value: new Float32Array([-1, -1]) },
        uClickTime: { value: -1 },
        uRippleSpeed: { value: rippleSpeed },
        uRippleThickness: { value: rippleThickness },
        uRippleIntensity: { value: rippleIntensityScale },
        uEdgeFade: { value: edgeFade },
        uLiquid: { value: liquid && !reduceMotion.matches ? 1 : 0 },
        uPointer: { value: new Float32Array([0.5, 0.5]) },
        uLiquidStrength: { value: liquidStrength },
        uLiquidRadius: { value: liquidRadius },
        uLiquidWobble: { value: liquidWobbleSpeed },
      },
    });
    const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });

    const resize = () => {
      const rect = container.getBoundingClientRect();
      renderer.setSize(Math.max(1, Math.floor(rect.width)), Math.max(1, Math.floor(rect.height)));
      const resolution = program.uniforms.uResolution.value as Float32Array;
      resolution[0] = gl.drawingBufferWidth;
      resolution[1] = gl.drawingBufferHeight;
      program.uniforms.uPixelSize.value = pixelSize * Math.min(window.devicePixelRatio || 1, 1.35);
      renderer.render({ scene: mesh });
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    resize();

    const pointer = program.uniforms.uPointer.value as Float32Array;
    const targetPointer = [0.5, 0.5];
    const updatePointer = (event: PointerEvent) => {
      targetPointer[0] = event.clientX / Math.max(window.innerWidth, 1);
      targetPointer[1] = 1 - event.clientY / Math.max(window.innerHeight, 1);
    };
    const addRipple = (event: PointerEvent) => {
      if (!enableRipples || reduceMotion.matches) return;
      const click = program.uniforms.uClickPos.value as Float32Array;
      click[0] = event.clientX / Math.max(window.innerWidth, 1);
      click[1] = 1 - event.clientY / Math.max(window.innerHeight, 1);
      program.uniforms.uClickTime.value = program.uniforms.uTime.value;
    };
    window.addEventListener("pointermove", updatePointer, { passive: true });
    window.addEventListener("pointerdown", addRipple, { passive: true });

    let animationFrame = 0;
    let isVisible = true;
    let isPageVisible = !document.hidden;
    const startedAt = performance.now();
    const draw = (time: number) => {
      program.uniforms.uTime.value = ((time - startedAt) * 0.001) * speed;
      pointer[0] += (targetPointer[0] - pointer[0]) * 0.055;
      pointer[1] += (targetPointer[1] - pointer[1]) * 0.055;
      renderer.render({ scene: mesh });
      if (!reduceMotion.matches) animationFrame = requestAnimationFrame(draw);
      else animationFrame = 0;
    };
    const stop = () => {
      if (animationFrame) cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    };
    const start = () => {
      if (isVisible && isPageVisible && animationFrame === 0) animationFrame = requestAnimationFrame(draw);
    };
    const syncMotion = () => {
      program.uniforms.uEnableRipples.value = enableRipples && !reduceMotion.matches ? 1 : 0;
      program.uniforms.uLiquid.value = liquid && !reduceMotion.matches ? 1 : 0;
      stop();
      start();
      if (reduceMotion.matches) renderer.render({ scene: mesh });
    };
    const intersectionObserver = new IntersectionObserver(([entry]) => {
      isVisible = entry.isIntersecting;
      if (isVisible) start();
      else stop();
    });
    intersectionObserver.observe(container);
    const onVisibilityChange = () => {
      isPageVisible = !document.hidden;
      if (isPageVisible) start();
      else stop();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    reduceMotion.addEventListener("change", syncMotion);
    start();

    return () => {
      stop();
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener("visibilitychange", onVisibilityChange);
      reduceMotion.removeEventListener("change", syncMotion);
      window.removeEventListener("pointermove", updatePointer);
      window.removeEventListener("pointerdown", addRipple);
      if (canvas.parentElement === container) container.removeChild(canvas);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, [
    color,
    edgeFade,
    enableRipples,
    liquid,
    liquidRadius,
    liquidStrength,
    liquidWobbleSpeed,
    patternDensity,
    patternScale,
    pixelSize,
    pixelSizeJitter,
    rippleIntensityScale,
    rippleSpeed,
    rippleThickness,
    speed,
    transparent,
    variant,
  ]);

  return <div ref={containerRef} className={`pixel-blast-container${className ? ` ${className}` : ""}`} style={style} aria-hidden="true" />;
}
