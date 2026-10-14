// Firebase's reCAPTCHA callback (<scheme>://firebaseauth/link?...) is consumed
// natively by Firebase Auth; routing it lands on "Unmatched route".
export function redirectSystemPath({ path }: { path: string; initial: boolean }) {
  if (/^[\w.+-]+:\/\/firebaseauth\//.test(path) || path.startsWith('/firebaseauth/')) {
    return null;
  }
  return path;
}
