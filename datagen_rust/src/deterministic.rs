//! Deterministic primitives shared with the Python generator.
//!
//! `PythonRandom` is intentionally a compatibility implementation of
//! `random.Random` for non-negative integer seeds.  The source generator derives every
//! stream seed with [`stable_integer`], so supporting that seed form gives us the exact
//! CPython MT19937 state, `random()`, `_randbelow()`, `shuffle()`, `gauss()`,
//! `gammavariate()`, and `uniform()` behavior used by the Python implementation.

use sha2::{Digest, Sha256};
use uuid::Uuid;

const BC_NAMESPACE: Uuid = Uuid::from_u128(0x00000000_0000_0000_0000_0000513c0001);
const MT_N: usize = 624;
const MT_M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER_MASK: u32 = 0x8000_0000;
const LOWER_MASK: u32 = 0x7fff_ffff;

#[must_use]
pub fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

#[must_use]
pub fn stable_integer(parts: &[&str], modulo: u64) -> u64 {
    assert!(modulo > 0, "modulo must be positive");
    let mut hasher = Sha256::new();
    for (index, part) in parts.iter().enumerate() {
        if index > 0 {
            hasher.update(b"|");
        }
        hasher.update(part.as_bytes());
    }
    let digest = hasher.finalize();
    u64::from_be_bytes(digest[..8].try_into().expect("SHA-256 prefix")) % modulo
}

fn stable_integer_with_prefix(prefix: &str, parts: &[&str], modulo: u64) -> u64 {
    assert!(modulo > 0, "modulo must be positive");
    let mut hasher = Sha256::new();
    hasher.update(prefix.as_bytes());
    for part in parts {
        hasher.update(b"|");
        hasher.update(part.as_bytes());
    }
    let digest = hasher.finalize();
    u64::from_be_bytes(digest[..8].try_into().expect("SHA-256 prefix")) % modulo
}

#[must_use]
pub fn shopify_numeric(resource: &str, business_key: &str) -> u64 {
    1_000_000_000_000_000 + stable_integer(&[resource, business_key], 4_000_000_000_000_000_000)
}

#[must_use]
pub fn shopify_gid(resource: &str, business_key: &str) -> String {
    format!(
        "gid://shopify/{resource}/{}",
        shopify_numeric(resource, business_key)
    )
}

#[must_use]
pub fn shopify_order_name(sequence: u64) -> String {
    assert!(sequence > 0, "source sequence must be positive");
    format!("#{}", 1000 + sequence)
}

#[must_use]
pub fn bc_document_number(prefix: &str, business_key: &str) -> String {
    format!(
        "{prefix}-{:08}",
        stable_integer(&[business_key], 100_000_000)
    )
}

#[must_use]
pub fn bc_uuid(resource: &str, business_key: &str) -> String {
    Uuid::new_v5(
        &BC_NAMESPACE,
        format!("{resource}:{business_key}").as_bytes(),
    )
    .to_string()
}

/// CPython-compatible `random.Random` for integer seeds.
#[derive(Debug, Clone)]
pub struct PythonRandom {
    state: [u32; MT_N],
    index: usize,
    gauss_next: Option<f64>,
}

impl PythonRandom {
    /// Match `_random.Random.seed()` for a non-negative Python integer.
    #[must_use]
    pub fn from_u64(seed: u64) -> Self {
        let mut result = Self {
            state: [0; MT_N],
            index: MT_N,
            gauss_next: None,
        };
        let words = [seed as u32, (seed >> 32) as u32];
        let word_count = if seed > u64::from(u32::MAX) { 2 } else { 1 };
        result.init_by_array(&words[..word_count]);
        result
    }

    /// Match `retail_datagen.identity.rng(master_seed, *parts)`.
    #[must_use]
    pub fn new(master_seed: u64, parts: &[&str]) -> Self {
        let master = master_seed.to_string();
        Self::new_with_master(&master, parts)
    }

    /// Construct a Python-compatible stream while reusing the caller's cached
    /// decimal master-seed text. Hot causal loops otherwise allocate the same
    /// seed string and a temporary slice for every deterministic draw.
    #[must_use]
    pub fn new_with_master(master_seed: &str, parts: &[&str]) -> Self {
        Self::from_u64(stable_integer_with_prefix(
            master_seed,
            parts,
            i64::MAX as u64,
        ))
    }

    /// Construct the same stream when all seed components are already strings.
    #[must_use]
    pub fn from_parts(parts: &[&str]) -> Self {
        Self::from_u64(stable_integer(parts, i64::MAX as u64))
    }

    fn init_genrand(&mut self, seed: u32) {
        self.state[0] = seed;
        for index in 1..MT_N {
            self.state[index] = 1_812_433_253_u32
                .wrapping_mul(self.state[index - 1] ^ (self.state[index - 1] >> 30))
                .wrapping_add(index as u32);
        }
        self.index = MT_N;
    }

    fn init_by_array(&mut self, key: &[u32]) {
        debug_assert!(!key.is_empty());
        self.init_genrand(19_650_218);
        let mut i = 1_usize;
        let mut j = 0_usize;
        for _ in 0..MT_N.max(key.len()) {
            self.state[i] = (self.state[i]
                ^ (self.state[i - 1] ^ (self.state[i - 1] >> 30)).wrapping_mul(1_664_525))
            .wrapping_add(key[j])
            .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= MT_N {
                self.state[0] = self.state[MT_N - 1];
                i = 1;
            }
            if j >= key.len() {
                j = 0;
            }
        }
        for _ in 0..(MT_N - 1) {
            self.state[i] = (self.state[i]
                ^ (self.state[i - 1] ^ (self.state[i - 1] >> 30)).wrapping_mul(1_566_083_941))
            .wrapping_sub(i as u32);
            i += 1;
            if i >= MT_N {
                self.state[0] = self.state[MT_N - 1];
                i = 1;
            }
        }
        self.state[0] = 0x8000_0000;
        self.index = MT_N;
    }

    fn twist(&mut self) {
        for index in 0..MT_N {
            let y =
                (self.state[index] & UPPER_MASK) | (self.state[(index + 1) % MT_N] & LOWER_MASK);
            self.state[index] = self.state[(index + MT_M) % MT_N]
                ^ (y >> 1)
                ^ if y & 1 == 0 { 0 } else { MATRIX_A };
        }
        self.index = 0;
    }

    fn next_u32(&mut self) -> u32 {
        if self.index >= MT_N {
            self.twist();
        }
        let mut value = self.state[self.index];
        self.index += 1;
        value ^= value >> 11;
        value ^= (value << 7) & 0x9d2c_5680;
        value ^= (value << 15) & 0xefc6_0000;
        value ^ (value >> 18)
    }

    /// Match CPython's `_random.Random.random()` 53-bit construction.
    #[must_use]
    pub fn random(&mut self) -> f64 {
        let high = u64::from(self.next_u32() >> 5);
        let low = u64::from(self.next_u32() >> 6);
        ((high << 26) + low) as f64 * (1.0 / 9_007_199_254_740_992.0)
    }

    /// Compatibility alias used by the rest of the Rust engine.
    #[must_use]
    pub fn unit_f64(&mut self) -> f64 {
        self.random()
    }

    #[must_use]
    pub fn bool(&mut self, probability: f64) -> bool {
        self.random() < probability.clamp(0.0, 1.0)
    }

    /// Match `Random.getrandbits(k)` for `k <= 64`.
    #[must_use]
    pub fn getrandbits(&mut self, bits: u32) -> u64 {
        assert!(
            bits <= 64,
            "only up to 64 random bits are needed by datagen"
        );
        if bits == 0 {
            return 0;
        }
        if bits <= 32 {
            return u64::from(self.next_u32() >> (32 - bits));
        }
        let low = u64::from(self.next_u32());
        let remaining = bits - 32;
        let high = u64::from(self.next_u32() >> (32 - remaining));
        low | (high << 32)
    }

    /// Match Python's `_randbelow_with_getrandbits`.
    #[must_use]
    pub fn randbelow(&mut self, upper_exclusive: u64) -> u64 {
        assert!(upper_exclusive > 0, "empty random range");
        let bits = 64 - upper_exclusive.leading_zeros();
        loop {
            let value = self.getrandbits(bits);
            if value < upper_exclusive {
                return value;
            }
        }
    }

    #[must_use]
    pub fn range_u64(&mut self, start: u64, end_exclusive: u64) -> u64 {
        assert!(start < end_exclusive, "empty integer range");
        start + self.randbelow(end_exclusive - start)
    }

    pub fn shuffle<T>(&mut self, values: &mut [T]) {
        for index in (1..values.len()).rev() {
            let swap_with = self.randbelow((index + 1) as u64) as usize;
            values.swap(index, swap_with);
        }
    }

    #[must_use]
    pub fn uniform(&mut self, low: f64, high: f64) -> f64 {
        low + (high - low) * self.random()
    }

    /// Match `random.Random.gauss()` including its cached second variate.
    #[must_use]
    pub fn gauss(&mut self, mean: f64, standard_deviation: f64) -> f64 {
        let normal = if let Some(value) = self.gauss_next.take() {
            value
        } else {
            let angle = self.random() * std::f64::consts::TAU;
            let radius = (-2.0 * (1.0 - self.random()).ln()).sqrt();
            self.gauss_next = Some(angle.sin() * radius);
            angle.cos() * radius
        };
        mean + normal * standard_deviation
    }

    /// Match `random.Random.gammavariate(alpha, beta)` from CPython 3.12+.
    #[must_use]
    pub fn gammavariate(&mut self, alpha: f64, beta: f64) -> f64 {
        assert!(
            alpha > 0.0 && beta > 0.0,
            "gamma parameters must be positive"
        );
        const LOG4: f64 = 1.386_294_361_119_890_6;
        const SG_MAGICCONST: f64 = 2.504_077_396_776_274;
        if alpha > 1.0 {
            let ainv = (2.0 * alpha - 1.0).sqrt();
            let bbb = alpha - LOG4;
            let ccc = alpha + ainv;
            loop {
                let u1 = self.random();
                if !(1e-7..0.999_999_9).contains(&u1) {
                    continue;
                }
                let u2 = 1.0 - self.random();
                let v = (u1 / (1.0 - u1)).ln() / ainv;
                let x = alpha * v.exp();
                let z = u1 * u1 * u2;
                let r = bbb + ccc * v - x;
                if r + SG_MAGICCONST - 4.5 * z >= 0.0 || r >= z.ln() {
                    return x * beta;
                }
            }
        }
        if alpha == 1.0 {
            let mut u = self.random();
            while u <= 1e-7 {
                u = self.random();
            }
            return -u.ln() * beta;
        }
        loop {
            let u = self.random();
            let b = (std::f64::consts::E + alpha) / std::f64::consts::E;
            let p = b * u;
            let x = if p <= 1.0 {
                p.powf(1.0 / alpha)
            } else {
                -((b - p) / alpha).ln()
            };
            let u1 = self.random();
            if p > 1.0 {
                if u1 <= x.powf(alpha - 1.0) {
                    return x * beta;
                }
            } else if u1 <= (-x).exp() {
                return x * beta;
            }
        }
    }

    /// Match the generator's `_poisson` helper, including Python half-even `round`.
    #[must_use]
    pub fn poisson(&mut self, mean: f64) -> u64 {
        if mean <= 0.0 {
            return 0;
        }
        if mean > 25.0 {
            return round_half_even_f64(self.gauss(mean, mean.sqrt())).max(0.0) as u64;
        }
        let threshold = (-mean).exp();
        let mut product = 1.0;
        let mut count = 0_u64;
        while product > threshold {
            count += 1;
            product *= self.random();
        }
        count - 1
    }
}

/// Python-compatible half-even rounding for finite binary floats without an `ndigits` argument.
#[must_use]
pub fn round_half_even_f64(value: f64) -> f64 {
    if !value.is_finite() {
        return value;
    }
    let floor = value.floor();
    let fraction = value - floor;
    if fraction < 0.5 {
        floor
    } else if fraction > 0.5 {
        floor + 1.0
    } else if floor.rem_euclid(2.0) == 0.0 {
        floor
    } else {
        floor + 1.0
    }
}

pub type DeterministicRng = PythonRandom;

#[cfg(test)]
mod tests {
    use super::{
        DeterministicRng, PythonRandom, bc_document_number, bc_uuid, shopify_gid, stable_integer,
    };

    #[test]
    fn python_compatible_stable_identity_vectors() {
        assert_eq!(
            stable_integer(&["hello", "world"], i64::MAX as u64),
            6_171_017_133_022_546_663
        );
        assert_eq!(
            shopify_gid("Order", "order-1"),
            "gid://shopify/Order/482072883149740931"
        );
        assert_eq!(bc_document_number("INV", "order-1"), "INV-60000396");
        assert_eq!(
            bc_uuid("invoice", "order-1"),
            "51384d12-2bfe-5dfb-a69a-e0198b3eec9d"
        );
    }

    #[test]
    fn random_streams_match_cpython_golden_vectors() {
        let mut random = PythonRandom::new(20_260_806, &["catalog-margin", "gulf-engine-oil-001"]);
        let expected: [f64; 5] = [
            0.600_159_212_956_163_3,
            0.159_378_839_032_645_05,
            0.368_277_713_046_663_35,
            0.942_869_378_976_909_3,
            0.365_355_498_019_875_55,
        ];
        for value in expected {
            assert_eq!(random.random().to_bits(), value.to_bits());
        }
    }

    #[test]
    fn shuffle_gauss_and_gamma_match_cpython() {
        let mut shuffled: Vec<usize> = (0..12).collect();
        PythonRandom::new(20_260_806, &["shuffle", "fixture"]).shuffle(&mut shuffled);
        assert_eq!(shuffled, [1, 2, 4, 3, 7, 0, 11, 10, 8, 9, 5, 6]);

        let mut gaussian = PythonRandom::new(20_260_806, &["gauss", "fixture"]);
        for expected in [
            -0.214_857_245_315_231_f64,
            -1.550_003_070_157_473_9,
            -0.462_994_673_912_718_26,
            -1.456_360_811_156_447_7,
        ] {
            assert_eq!(gaussian.gauss(0.0, 1.25).to_bits(), expected.to_bits());
        }

        let mut gamma = PythonRandom::new(20_260_806, &["gamma", "fixture"]);
        for expected in [
            2.076_313_023_110_831_8_f64,
            4.849_147_856_784_083,
            20.256_814_473_458_867,
            9.233_171_096_428_071,
        ] {
            assert_eq!(gamma.gammavariate(2.3, 4.7).to_bits(), expected.to_bits());
        }
    }

    #[test]
    fn streams_are_repeatable() {
        let mut left = DeterministicRng::new(42, &["market", "day"]);
        let mut right = DeterministicRng::new(42, &["market", "day"]);
        for _ in 0..100 {
            assert_eq!(left.random(), right.random());
        }
    }
}
