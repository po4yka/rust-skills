#![cfg(loom)]
use loom::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

#[derive(Default)]
pub struct Mailbox {
    value: AtomicUsize,
    ready: AtomicBool,
}
impl Mailbox {
    pub fn publish(&self, value: usize) {
        self.value.store(value, Ordering::Relaxed);
        #[cfg(not(broken))]
        self.ready.store(true, Ordering::Release);
        #[cfg(broken)]
        self.ready.store(true, Ordering::Relaxed);
    }
    pub fn take(&self) -> Option<usize> {
        self.ready.load(Ordering::Acquire).then(|| self.value.load(Ordering::Relaxed))
    }
}

#[test]
fn reader_sees_published_value() {
    use loom::{sync::Arc, thread};
    loom::model(|| {
        let mailbox = Arc::new(Mailbox::default());
        let writer = {
            let mailbox = Arc::clone(&mailbox);
            thread::spawn(move || mailbox.publish(42))
        };
        if let Some(value) = mailbox.take() {
            assert_eq!(value, 42);
        }
        writer.join().unwrap();
    });
}
