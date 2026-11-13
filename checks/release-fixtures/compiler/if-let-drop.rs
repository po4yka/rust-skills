use std::cell::RefCell;
use std::rc::Rc;
struct Record(&'static str, Rc<RefCell<Vec<&'static str>>>);
impl Drop for Record {
    fn drop(&mut self) { self.1.borrow_mut().push(self.0); }
}
fn main() {
    let log = Rc::new(RefCell::new(Vec::new()));
    {
        let pair = (Record("kept", log.clone()), Record("moved", log.clone()));
        #[allow(irrefutable_let_patterns)]
        let consume = || {
            if let (_, value) = pair { drop(value); }
        };
        drop(consume);
        #[cfg(modern)]
        assert_eq!(*log.borrow(), ["moved"]);
        #[cfg(not(modern))]
        assert_eq!(*log.borrow(), ["kept", "moved"]);
    }
    #[cfg(modern)]
    assert_eq!(*log.borrow(), ["moved", "kept"]);
    #[cfg(not(modern))]
    assert_eq!(*log.borrow(), ["kept", "moved"]);
}
