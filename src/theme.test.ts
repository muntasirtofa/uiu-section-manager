// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';

describe('theme preference', () => {
  it('stores and reads the selected theme', () => {
    localStorage.setItem('uiu-theme', 'dark');
    expect(localStorage.getItem('uiu-theme')).toBe('dark');
  });
});
