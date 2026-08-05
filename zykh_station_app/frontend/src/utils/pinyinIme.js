let enginePromise;

export function loadPinyinEngine() {
  if (!enginePromise) {
    enginePromise = Promise.all([
      import("pinyin-ime"),
      import("pinyin-ime/dictionary/google_pinyin_dict")
    ]).then(([{ createPinyinEngine }, { dict }]) => createPinyinEngine(dict));
  }
  return enginePromise;
}
