// Outro A "數據流": teal data grid, the logo draws itself, name + slogan, three action chips with line icons.
import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {C, FONT, FONT_EN, Icon, Mark, p} from './Brand';

const Grid: React.FC<{f: number}> = ({f}) => {
  const dots = [];
  for (let y = 0; y < 1920; y += 48) {
    for (let x = 24; x < 1080; x += 48) {
      // a diagonal wave of brighter dots passes through, like data moving
      const wave = Math.max(0, 1 - Math.abs(((x + y) / 900 - f / 40) % 2.4 - 1) * 3);
      dots.push(<circle key={`${x}-${y}`} cx={x} cy={y} r={2 + wave * 1.6} fill={wave > 0.05 ? C.mint : '#1d3b3a'} opacity={0.25 + wave * 0.6} />);
    }
  }
  return <svg width={1080} height={1920} style={{position: 'absolute', opacity: p(f, 0, 14)}}>{dots}</svg>;
};

const Chip: React.FC<{f: number; at: number; kind: 'follow' | 'like' | 'share'; label: string}> = ({f, at, kind, label}) => {
  const k = p(f, at, 14);
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 14, padding: '18px 30px', borderRadius: 999,
      border: `2px solid ${C.mint}${Math.round(40 + 120 * k).toString(16)}`, background: `${C.tealDark}cc`,
      transform: `translateY(${(1 - k) * 30}px) scale(${0.9 + 0.1 * k})`, opacity: k}}>
      <Icon kind={kind} size={46} draw={p(f, at + 4, 14)} color={C.mint} />
      <span style={{fontFamily: FONT, fontSize: 40, fontWeight: 700, color: C.text}}>{label}</span>
    </div>
  );
};

// speed > 1 compresses the same choreography (3 s cut: speed 4/3)
export const O1: React.FC<{speed?: number}> = ({speed = 1}) => {
  const f = useCurrentFrame() * speed;
  const name = p(f, 30, 16);
  const pulse = 10 + 8 * Math.sin(f / 9);
  return (
    <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 42%, ${C.tealDark} 0%, ${C.bg} 62%)`}}>
      <Grid f={f} />
      <AbsoluteFill style={{alignItems: 'center', top: 520}}>
        <div style={{transform: `scale(${interpolate(p(f, 4, 40), [0, 1], [0.85, 1])})`}}>
          <Mark size={300} draw={p(f, 4, 30)} fill={p(f, 28, 16)} eye={p(f, 40, 10)} glow={f > 40 ? pulse : 0} />
        </div>
        <div style={{marginTop: 40, fontFamily: FONT, fontSize: 92, fontWeight: 900, color: C.text, letterSpacing: 8,
          opacity: name, transform: `translateY(${(1 - name) * 40}px)`}}>桑尼資料科學</div>
        <div style={{marginTop: 6, fontFamily: FONT_EN, fontSize: 30, fontWeight: 600, color: C.mint,
          letterSpacing: interpolate(name, [0, 1], [2, 14]), opacity: name}}>SUNNY DATA SCIENCE</div>
        <div style={{marginTop: 48, fontFamily: FONT, fontSize: 46, fontWeight: 500, color: C.text, opacity: p(f, 46, 12)}}>
          用數據，看懂科技大事。
        </div>
        <div style={{display: 'flex', gap: 22, marginTop: 70}}>
          <Chip f={f} at={60} kind="follow" label="追蹤" />
          <Chip f={f} at={68} kind="like" label="按讚" />
          <Chip f={f} at={76} kind="share" label="分享" />
        </div>
        <div style={{marginTop: 34, fontFamily: FONT, fontSize: 32, color: C.sub, opacity: p(f, 86, 12)}}>
          每週拆解一則科技大事
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
