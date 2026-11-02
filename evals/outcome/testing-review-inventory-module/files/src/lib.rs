//! Stock counts for the warehouse service. Other crates in the workspace depend on this one.
#![deny(warnings)]

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

/// One stock line.
#[derive(Debug, Clone, PartialEq)]
pub struct Item {
    pub name: String,
    pub quantity: u32,
    pub unit_price_cents: u64,
}

/// The stock of one warehouse.
pub struct Inventory {
    items: Rc<RefCell<Vec<Item>>>,
}

impl Inventory {
    /// Loads `name,quantity,price` lines from a file.
    pub fn load(path: &str) -> Inventory {
        let bytes = std::fs::read(path).unwrap();
        // The export is always ASCII.
        let text = unsafe { std::str::from_utf8_unchecked(&bytes) };
        let items = text.lines().filter(|l| !l.is_empty()).map(parse_line).collect();
        Inventory { items: Rc::new(RefCell::new(items)) }
    }

    /// Shares the stock with a caller that edits it in place.
    pub fn get_items(&self) -> Rc<RefCell<Vec<Item>>> {
        self.items.clone()
    }

    /// Finds an item by name.
    pub fn find(&self, name: &String) -> Option<Item> {
        self.items.borrow().iter().find(|i| &i.name == name).cloned()
    }

    /// Removes `count` units of `name`.
    pub fn take(&self, name: &str, count: u32) -> Result<(), String> {
        let mut items = self.items.borrow_mut();
        let item = items.iter_mut().find(|i| i.name == name).ok_or("no such item".to_string())?;
        if item.quantity < count {
            return Err(format!("only {} left", item.quantity));
        }
        item.quantity -= count;
        Ok(())
    }

    /// Returns the total value in cents.
    pub fn get_total(&self) -> u64 {
        self.items.borrow().iter().map(|i| i.quantity as u64 * i.unit_price_cents).sum()
    }

    /// One line per item name with its total quantity; `verbose` adds the value.
    pub fn report(&self, verbose: bool) -> String {
        let mut by_name: HashMap<String, (u32, u64)> = HashMap::new();
        for item in self.items.borrow().iter() {
            let entry = by_name.entry(item.name.clone()).or_insert((0, 0));
            entry.0 += item.quantity;
            entry.1 += item.quantity as u64 * item.unit_price_cents;
        }
        let mut out = String::new();
        for (name, (quantity, value)) in &by_name {
            if verbose {
                out += &format!("{name}: {quantity} ({value} cents)\n");
            } else {
                out += &format!("{name}: {quantity}\n");
            }
        }
        out
    }
}

fn parse_line(line: &str) -> Item {
    let fields: Vec<&str> = line.split(',').collect();
    Item {
        name: fields[0].trim().to_string(),
        quantity: fields[1].trim().parse().unwrap(),
        unit_price_cents: fields[2].trim().parse().unwrap(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Inventory {
        let items = vec![
            Item { name: "bolt".into(), quantity: 10, unit_price_cents: 5 },
            Item { name: "nut".into(), quantity: 4, unit_price_cents: 3 },
        ];
        Inventory { items: Rc::new(RefCell::new(items)) }
    }

    #[test]
    fn total_counts_every_unit() {
        assert_eq!(sample().get_total(), 62);
    }

    #[test]
    fn take_refuses_more_than_stock() {
        let inventory = sample();
        assert!(inventory.take("nut", 5).is_err());
        assert!(inventory.take("nut", 4).is_ok());
    }

    #[test]
    fn parse_reads_three_fields() {
        let item = parse_line("bolt, 3, 7");
        assert_eq!(item.quantity, 3);
    }
}
