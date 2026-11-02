//! An in-memory cache of rendered templates, shared by the request handlers.

use std::collections::HashMap;
use std::sync::Mutex;

/// Rendered pages, keyed by template name.
#[derive(Debug, Default)]
pub struct TemplateCache {
    rendered: Mutex<HashMap<String, String>>,
}

impl TemplateCache {
    /// Creates an empty cache.
    pub fn new() -> Self {
        Self::default()
    }

    /// Returns the rendered page for `name`. On a miss, calls `render` and stores the result.
    pub fn get_or_render(&self, name: &str, render: impl FnOnce(&str) -> String) -> String {
        match self.rendered.lock().expect("cache mutex poisoned").get(name) {
            Some(page) => page.clone(),
            None => {
                let page = render(name);
                self.rendered
                    .lock()
                    .expect("cache mutex poisoned")
                    .insert(name.to_owned(), page.clone());
                page
            }
        }
    }

    /// Returns the number of cached pages.
    pub fn len(&self) -> usize {
        self.rendered.lock().expect("cache mutex poisoned").len()
    }

    /// Returns true if no page is cached.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_new_cache_is_empty() {
        assert!(TemplateCache::new().is_empty());
    }

    #[test]
    fn renders_once_then_hits_the_cache() {
        let cache = TemplateCache::new();
        let mut calls = 0;
        let first = cache.get_or_render("home", |name| {
            calls += 1;
            format!("<h1>{name}</h1>")
        });
        let second = cache.get_or_render("home", |_| unreachable!("the page is cached"));
        assert_eq!(first, "<h1>home</h1>");
        assert_eq!(second, first);
        assert_eq!(calls, 1);
        assert_eq!(cache.len(), 1);
    }
}
