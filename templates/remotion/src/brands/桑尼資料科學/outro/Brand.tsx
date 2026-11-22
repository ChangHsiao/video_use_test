// Shared brand pieces for the outro options: CIS colors, the logo mark drawn from images/dark.svg
// (background square removed so the mark sits on any surface), and small motion helpers.
import React from 'react';
import {Easing, interpolate} from 'remotion';

export const C = {
  bg: '#050505',
  teal: '#2C918C',
  tealDark: '#0F2D2B',
  mint: '#7DE4D3',
  shade: '#47696F',
  red: '#BA4D43',
  navy: '#1E3A5F',
  text: '#FFFFFF',
  sub: '#9CA3AF',
};

export const FONT = '"Noto Sans TC", "Microsoft JhengHei", sans-serif';
export const FONT_EN = '"Inter", "Noto Sans TC", sans-serif';

export const ease = Easing.bezier(0.22, 1, 0.36, 1);
export const p = (f: number, start: number, len: number) =>
  interpolate(f, [start, start + len], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

const SHADE =
  'M29.53 59C29.5217 59 29.513 59 29.5047 59H27.0065C26.9736 59 26.9409 58.9998 26.9081 58.9991L22.1862 58.9049C19.51 58.8516 17.3686 56.674 17.3686 54.0061C17.3686 51.3381 17.5 51 18.6868 49.3615C20.4498 47.4902 14.1464 49.0792 14 40.6608C16.5882 40.6371 21.9622 41.2412 21.9455 46.6462C21.9416 47.8865 21.9455 54.0061 21.9455 54.0061C21.9455 54.1899 22.093 54.3401 22.2775 54.3439L26.9994 54.4381H27.0062H28.8827C31.5262 52.8032 32.9785 50.9465 33.5182 49.0645C34.3027 46.3284 33.1174 43.6724 31.4715 42.2257C28.9255 39.988 23.2151 34.7531 20.0427 31.836C18.1518 30.1015 17.0758 27.657 17.0758 25.0956L17.0755 19.5841C17.0755 18.103 17.6658 16.6826 18.7165 15.6356C19.7671 14.5883 21.192 14 22.6778 14H39.7302C44.8409 14 49.7423 16.0236 53.356 19.6256C56.9699 23.2277 59 28.1132 59 33.2072V39.7929C59 50.4007 50.3727 59 39.7302 59H29.53ZM35.7718 54.4379H39.7307C47.8453 54.4379 54.4236 47.8811 54.4236 39.7929V33.2072C54.4236 29.323 52.8757 25.5979 50.1202 22.8514C47.3647 20.1049 43.6275 18.5619 39.7307 18.5619H22.6783C22.4063 18.5619 22.1456 18.6696 21.9532 18.8614C21.7609 19.0531 21.6528 19.313 21.6528 19.5841L21.653 25.0952C21.653 26.3809 22.1932 27.6082 23.1423 28.4788L23.1443 28.4806C26.2976 31.3801 31.9698 36.5806 34.4988 38.8034C37.2683 41.2376 39.239 45.7137 37.9191 50.3175C37.5263 51.6873 36.8408 53.0846 35.7718 54.4379Z';
const MAIN =
  'M21.7091 30.9482C21.756 32.8813 23.664 35.1377 23.664 35.1377C23.664 35.1377 19.8839 31.7385 19.3219 31.2102C17.89 29.8655 17.0778 27.9874 17.0778 26.0218V19.5841C17.0778 18.103 17.6652 16.6826 18.711 15.6356C19.7567 14.5883 21.1748 14 22.6537 14H39.6259C44.7125 14 49.5909 16.0236 53.1876 19.6256C56.7845 23.2277 59 28.406 59 33.5V40C59 50.6078 50.2183 59 39.6259 59H26.9617C26.929 59 26.8965 58.9998 26.8638 58.9991L22.1641 58.9049C19.5006 58.8516 17.3692 56.674 17.3692 54.0061C17.3692 53.1693 17.3692 52.1142 17.515 51.5694C18.1871 54.301 22.0716 54.3401 22.2553 54.3439L26.955 54.4381H26.9617H39.6259C47.7023 54.4381 54.5 47.5883 54.5 39.5V33.5C54.5 29.6159 52.709 25.5981 49.9665 22.8516C47.224 20.1051 43.5044 18.5621 39.6259 18.5621H22.6537C22.383 18.5621 22.1235 18.6698 21.932 18.8616C21.7407 19.0533 21.6331 19.3133 21.6331 19.5843V25.438C21.6331 25.997 21.6822 29.8414 21.7091 30.9482Z';

/** Logo mark. draw: 0..1 outline stroke, fill: 0..1 body fill, eye: 0..1 eye pop, glow: px. */
export const Mark: React.FC<{size: number; draw: number; fill: number; eye: number; glow?: number}> = ({
  size, draw, fill, eye, glow = 0,
}) => (
  <svg width={size} height={size} viewBox="12 12 49 49" style={{overflow: 'visible', filter: glow ? `drop-shadow(0 0 ${glow}px ${C.mint}88)` : undefined}}>
    <path d={SHADE} fill={C.shade} fillRule="evenodd" opacity={fill} />
    <path d={MAIN} fill={C.mint} fillRule="evenodd" opacity={fill} />
    <path d={MAIN} fill="none" stroke={C.mint} strokeWidth={0.7} pathLength={1}
          strokeDasharray={1} strokeDashoffset={1 - draw} opacity={1 - fill * 0.9} />
    <circle cx={31.18} cy={24.64} r={3.27 * eye} fill="#fff" />
  </svg>
);

/** Action icons as line drawings, so they animate like the logo instead of looking pasted. */
export const Icon: React.FC<{kind: 'follow' | 'like' | 'share'; size: number; draw: number; color: string}> = ({
  kind, size, draw, color,
}) => {
  const d = {
    follow: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5M19 4v6M16 7h6',
    like: 'M7 10v11M7 10l4-7c1.7 0 2.6 1.3 2.2 3L12.6 10H19c1.2 0 2 1.1 1.8 2.2l-1.4 7A2.2 2.2 0 0 1 17.3 21H7M7 10H4v11h3',
    share: 'M14 4l7 7-7 7M21 11H9a6 6 0 0 0-6 6v3',
  }[kind];
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d={d} stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
    </svg>
  );
};
