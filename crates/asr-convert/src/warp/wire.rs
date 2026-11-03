use crate::{Error, Result};

pub fn warp_tool_name(field: u32) -> &'static str {
    match field {
        2 => "run_shell_command",
        3 => "search_codebase",
        5 => "read_files",
        6 => "apply_file_diffs",
        7 => "suggest_plan",
        8 => "suggest_create_plan",
        9 => "grep",
        11 => "read_mcp_resource",
        12 => "call_mcp_tool",
        13 => "write_to_long_running_shell_command",
        14 => "suggest_new_conversation",
        15 => "file_glob",
        17 => "open_code_review",
        18 => "init_project",
        19 => "subagent",
        20 => "read_documents",
        21 => "edit_documents",
        22 => "create_documents",
        23 => "read_shell_command_output",
        24 => "use_computer",
        26 => "read_skill",
        28 => "fetch_conversation",
        29 => "start_agent",
        30 => "send_message_to_agent",
        31 => "transfer_shell_command_control_to_user",
        _ => "unknown",
    }
}

pub fn is_warp_tool_arm(field: u32) -> bool {
    matches!(field, 2..=28 | 30..=32 | 34..=38)
}

pub fn is_warp_tool_result_arm(field: u32) -> bool {
    matches!(field, 2..=10 | 14..=32 | 34..=36 | 38..=42)
}

#[derive(Clone, Copy, Debug)]
pub enum WarpWireValue<'a> {
    Varint(u64),
    Fixed64(u64),
    LengthDelimited(&'a [u8]),
    Fixed32,
}

#[derive(Clone, Copy, Debug)]
pub struct WarpWireField<'a> {
    pub number: u32,
    pub value: WarpWireValue<'a>,
}

pub struct WarpWireCursor<'a> {
    data: &'a [u8],
    position: usize,
}

impl<'a> WarpWireCursor<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Self { data, position: 0 }
    }

    pub fn next_field(&mut self) -> Result<Option<WarpWireField<'a>>> {
        if self.position == self.data.len() {
            return Ok(None);
        }
        let key = read_varint(self.data, &mut self.position)?;
        let number = u32::try_from(key >> 3)
            .map_err(|_| Error::Invalid("Warp protobuf field number overflowed".to_owned()))?;
        if number == 0 {
            return Err(Error::Invalid(
                "Warp protobuf field number must be nonzero".to_owned(),
            ));
        }
        let wire_type = (key & 0x07) as u8;
        let value = match wire_type {
            0 => WarpWireValue::Varint(read_varint(self.data, &mut self.position)?),
            1 => {
                let bytes: [u8; 8] = self
                    .take(8, "fixed64")?
                    .try_into()
                    .map_err(|_| Error::Invalid("Warp fixed64 width changed".into()))?;
                WarpWireValue::Fixed64(u64::from_le_bytes(bytes))
            }
            2 => {
                let length =
                    usize::try_from(read_varint(self.data, &mut self.position)?).map_err(|_| {
                        Error::Invalid("Warp protobuf length exceeds the platform range".to_owned())
                    })?;
                WarpWireValue::LengthDelimited(self.take(length, "length-delimited field")?)
            }
            5 => {
                let _ = self.take(4, "fixed32")?;
                WarpWireValue::Fixed32
            }
            other => {
                return Err(Error::Invalid(format!(
                    "unsupported Warp protobuf wire type {other}"
                )))
            }
        };
        Ok(Some(WarpWireField { number, value }))
    }

    fn take(&mut self, length: usize, label: &str) -> Result<&'a [u8]> {
        let end = self
            .position
            .checked_add(length)
            .ok_or_else(|| Error::Invalid(format!("overflow while decoding Warp {label}")))?;
        if end > self.data.len() {
            return Err(Error::Invalid(format!(
                "truncated {label} in Warp protobuf"
            )));
        }
        let value = &self.data[self.position..end];
        self.position = end;
        Ok(value)
    }
}

fn read_varint(data: &[u8], position: &mut usize) -> Result<u64> {
    let mut value = 0_u64;
    for shift in (0..70).step_by(7) {
        let byte = *data
            .get(*position)
            .ok_or_else(|| Error::Invalid("truncated varint in Warp protobuf".to_owned()))?;
        *position += 1;
        if shift == 63 && byte & 0xfe != 0 {
            return Err(Error::Invalid(
                "oversized varint in Warp protobuf".to_owned(),
            ));
        }
        value |= u64::from(byte & 0x7f) << shift;
        if byte & 0x80 == 0 {
            return Ok(value);
        }
    }
    Err(Error::Invalid(
        "oversized varint in Warp protobuf".to_owned(),
    ))
}
