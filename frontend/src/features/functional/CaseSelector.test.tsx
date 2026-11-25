import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
// @ts-expect-error Node is available in Vitest; the browser project omits Node typings.
import { readFileSync } from 'node:fs';
import { CaseSelector } from './CaseSelector';
const stylesheet = document.createElement('style');
afterEach(() => stylesheet.remove());

test('guided case checkbox stays beside its text and clicking the name selects it', () => {
  const onChange = vi.fn();
  stylesheet.textContent = readFileSync('src/styles.css', 'utf8') + readFileSync('src/features/functional/functional.css', 'utf8');
  document.head.appendChild(stylesheet);
  render(<div className="guided-functional">
    <CaseSelector modules={{quota:[{path:'smoke/capacity.yaml',name:'verify_fs_capacity',description:'验证容量'}]}}
      selected={{}} onChange={onChange} />
  </div>);
  const name = screen.getByText('verify_fs_capacity');
  const row = name.closest('label')!;
  expect(getComputedStyle(row).display).toBe('flex');
  expect(getComputedStyle(row).flexDirection).toBe('row');
  expect(getComputedStyle(row).alignItems).toBe('flex-start');
  expect(row.firstElementChild?.tagName).toBe('INPUT');
  fireEvent.click(name);
  expect(onChange).toHaveBeenCalledWith({quota:['smoke/capacity.yaml']});
});
