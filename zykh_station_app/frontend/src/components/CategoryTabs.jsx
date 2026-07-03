import React from "react";

const defaultCategories = ["全部", "慢病常用", "感冒发热", "肠胃", "过敏", "外伤消毒"];

export function CategoryTabs({ categories = defaultCategories, activeCategory, onChange }) {
  const items = categories.length ? categories : defaultCategories;
  return (
    <div className="category-tabs" role="tablist" aria-label="药品分类">
      {items.map((category) => (
        <button
          key={category}
          type="button"
          role="tab"
          aria-selected={activeCategory === category}
          className={activeCategory === category ? "active" : ""}
          onClick={() => onChange(category)}
        >
          {category}
        </button>
      ))}
    </div>
  );
}
