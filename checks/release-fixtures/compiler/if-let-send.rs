use std::rc::Rc;
fn requires_send(_: impl Send) {}
fn main() {
    let pair = (Rc::new(1), String::from("moved"));
    #[allow(irrefutable_let_patterns)]
    let consume = move || {
        if let (_, value) = pair {
            drop(value);
        }
    };
    requires_send(consume);
}
