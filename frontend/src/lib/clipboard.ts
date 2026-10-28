/**
 * 复制失败（权限被拒、非安全上下文）时返回 false，让调用方自己决定要不要显示成功态。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
