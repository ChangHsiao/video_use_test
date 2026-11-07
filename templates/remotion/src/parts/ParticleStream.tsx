// 粒子流：從一點往一個方向連續噴出小點，越飛越散、越大、越淡；用來畫氣體、水流、熱、看不見的流動

import React from 'react';
import {useCurrentFrame} from 'remotion';
import {theme} from '../theme';
import {rand} from './motion';

type Dir = 'left' | 'right' | 'up' | 'down';
const VEC: Record<Dir, [number, number]> = {left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1]};

// (x, y) 是噴出口；每 interval 格生一顆，每顆活 life 格；seed 換一個數字就是另一組亂數
export const ParticleStream: React.FC<{
  x: number; y: number; dir: Dir; start: number;
  count?: number; interval?: number; life?: number;
  gap?: number; speed?: number; speedJitter?: number;
  spread?: number; spreadGrow?: number;
  size?: number; sizeGrow?: number; opacity?: number;
  color?: string; fill?: string; seed?: number; glow?: boolean;
}> = ({
  x, y, dir, start, count = 260, interval = 0.5, life = 22, gap = 0, speed = 22, speedJitter = 6,
  spread = 6, spreadGrow = 1.6, size = 4, sizeGrow = 10, opacity = 0.7,
  color = theme.colors.cyan, fill, seed = 0, glow = true,
}) => {
  const frame = useCurrentFrame();
  const [dx, dy] = VEC[dir];
  const dots = [];
  for (let i = 0; i < count; i++) {
    const age = frame - (start + i * interval);
    if (age < 0 || age > life) continue;
    const t = age / life;
    const side = (rand(i + seed) - 0.5) * 2; // 往兩側偏多少：-1～1
    const along = gap + age * (speed + rand(i + seed + 100) * speedJitter);
    const across = side * (spread + age * spreadGrow); // 水平噴時往上下散，垂直噴時往左右散
    dots.push(
      <circle key={i} cx={x + dx * along + (dy !== 0 ? across : 0)} cy={y + dy * along + (dx !== 0 ? across : 0)}
        r={size + t * sizeGrow} fill={fill ?? color} opacity={(1 - t) * opacity} />,
    );
  }
  return <g filter={glow ? 'url(#glow)' : undefined}>{dots}</g>;
};
