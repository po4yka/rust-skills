//! A single-slot mailbox between exactly one producer thread and one consumer thread.
//!
//! The producer calls [`Mailbox::publish`]; the consumer calls [`Mailbox::take`].

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

/// One slot that holds at most one value.
#[derive(Debug, Default)]
pub struct Mailbox {
    value: AtomicU64,
    full: AtomicBool,
}

impl Mailbox {
    /// Creates an empty mailbox.
    pub const fn new() -> Self {
        Self { value: AtomicU64::new(0), full: AtomicBool::new(false) }
    }

    /// Puts `v` in the slot. Returns false, and changes nothing, if the slot is full.
    pub fn publish(&self, v: u64) -> bool {
        if self.full.load(Ordering::Relaxed) {
            return false;
        }
        self.value.store(v, Ordering::Relaxed);
        self.full.store(true, Ordering::Relaxed);
        true
    }

    /// Removes and returns the value in the slot, or `None` if the slot is empty.
    pub fn take(&self) -> Option<u64> {
        if !self.full.load(Ordering::Relaxed) {
            return None;
        }
        let v = self.value.load(Ordering::Relaxed);
        self.full.store(false, Ordering::Relaxed);
        Some(v)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_empty_mailbox_has_nothing_to_take() {
        assert_eq!(Mailbox::new().take(), None);
    }

    #[test]
    fn take_returns_the_published_value_once() {
        let mailbox = Mailbox::new();
        assert!(mailbox.publish(7));
        assert_eq!(mailbox.take(), Some(7));
        assert_eq!(mailbox.take(), None);
    }

    #[test]
    fn publish_refuses_a_full_slot() {
        let mailbox = Mailbox::new();
        assert!(mailbox.publish(1));
        assert!(!mailbox.publish(2));
        assert_eq!(mailbox.take(), Some(1));
    }
}
