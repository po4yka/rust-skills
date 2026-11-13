fn main() {
    let pair = (String::from("kept"), String::from("moved"));
    #[allow(irrefutable_let_patterns)]
    let consume = || {
        if let (_, value) = pair {
            assert_eq!(value, "moved");
        }
    };
    assert_eq!(pair.0, "kept");
    consume();
}
