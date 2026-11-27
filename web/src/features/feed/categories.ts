// Press category bar rules (task 9.5). Pure, so the bar and the feed agree on what is selected.
import type { CategoryCount } from "@/src/api/client";

/** Categories to show as chips: none unless at least two have stories (one chip filters nothing). */
export function barCategories(categories: readonly CategoryCount[] | undefined): CategoryCount[] {
  const withStories = (categories ?? []).filter((c) => c.stories > 0);
  return withStories.length >= 2 ? withStories : [];
}

/**
 * The category the feed filters by, from the URL's ``?category=``. While the list is still loading
 * the link is trusted, so a shared filtered link loads filtered; once loaded, an unknown name means All.
 */
export function activeCategory(
  param: string | null,
  categories: readonly CategoryCount[] | undefined,
): string | null {
  if (!param) return null;
  if (categories === undefined) return param;
  return categories.some((c) => c.name === param) ? param : null;
}

/** The feed URL for a category (null = All), keeping any other query params. */
export function categoryHref(category: string | null, search: string): string {
  const params = new URLSearchParams(search);
  if (category) params.set("category", category);
  else params.delete("category");
  const qs = params.toString();
  return qs ? `/?${qs}` : "/";
}
