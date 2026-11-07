// 範例動畫：水為什麼會沸騰。示範零件怎麼組、時間怎麼用字幕文字查；只學寫法，主題和構圖不要照抄
//
// 時間來自 public/example_cues.json（假的旁白）。正式做時改成 useCueTimer('這段第一句字幕')，
// 算繪加 --public-dir ..，就會讀 edit/cues.json。

import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Arrow, Background, Callout, Canvas, DiagramBadge, ParticleStream, Title, drawStroke, progress, useCueTimer} from '../parts';
import {theme} from '../theme';

const {red, cyan, amber, line, muted} = theme.colors;

// 主題專屬的圖形：鍋子（自己畫，零件庫不提供）
const POT = {left: 300, right: 780, top: 980, bottom: 1300};
const WATER_TOP = 1040;

export const Boiling: React.FC = () => {
  const frame = useCurrentFrame();
  // 這段動畫從「把一壺水放上爐子」那句開始；at(文字) 是念到那句時的格數
  const at = useCueTimer('把一壺水放上爐子', 'example_cues.json');
  const heat = at('底部的水先變熱');
  const bubbles = at('變成水蒸氣泡');
  const steam = at('冒出蒸氣');

  const draw = progress(frame, 6, 24);
  const water = progress(frame, 20, 16);
  const flame = progress(frame, heat, 10);

  return (
    <Background>
      <Title small="示範動畫" big="水為什麼會沸騰" accent="沸騰" />
      <DiagramBadge />
      <Canvas defs={
        <linearGradient id="water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={cyan} stopOpacity={0.35} />
          <stop offset="100%" stopColor={cyan} stopOpacity={0.12} />
        </linearGradient>
      }>
        {/* 水和鍋子：鍋身一筆畫出來，水再淡入 */}
        <rect x={POT.left + 6} y={WATER_TOP} width={POT.right - POT.left - 12} height={POT.bottom - WATER_TOP - 6}
          fill="url(#water)" opacity={water} />
        <path d={`M${POT.left} ${POT.top} L${POT.left} ${POT.bottom} L${POT.right} ${POT.bottom} L${POT.right} ${POT.top}`}
          fill="none" stroke={line} strokeWidth={8} strokeLinejoin="round" {...drawStroke(draw)} />

        {/* 爐火：三團火焰，出現後一直閃 */}
        {[420, 540, 660].map((x, k) => {
          const h = 60 + Math.sin(frame * 0.6 + k * 2) * 12;
          return (
            <path key={x} d={`M${x - 34} 1380 Q${x} ${1380 - h * 2} ${x + 34} 1380 Z`} fill={amber}
              opacity={flame * 0.9} filter="url(#glow)" />
          );
        })}
        <Arrow x={220} y={1400} dir="up" len={120} start={heat} color={red} text="加熱" />

        {/* 氣泡：從鍋底往上浮到水面 */}
        {[400, 540, 680].map((x, k) => (
          <ParticleStream key={x} x={x} y={POT.bottom - 20} dir="up" start={bubbles + k * 4}
            count={40} interval={4} life={34} speed={7} speedJitter={1} spread={4} spreadGrow={0.3}
            size={7} sizeGrow={6} opacity={0.9} color="#e8f7ff" seed={k * 50} glow={false} />
        ))}
        <Callout x={560} y={1150} tx={880} ty={1180} text="水蒸氣泡" color={cyan} start={bubbles + 10} fontSize={48} />

        {/* 蒸氣：從水面往上冒，越飄越大、越淡 */}
        {[440, 540, 640].map((x, k) => (
          <ParticleStream key={x} x={x} y={WATER_TOP - 10} dir="up" start={steam + k * 3}
            count={60} interval={2} life={40} speed={6} speedJitter={2} spread={10} spreadGrow={1.2}
            size={10} sizeGrow={30} opacity={0.35} color={muted} seed={300 + k * 50} />
        ))}
        <Callout x={600} y={880} tx={860} ty={760} text="蒸氣" color={line} start={steam + 6} fontSize={48} />
      </Canvas>
    </Background>
  );
};
