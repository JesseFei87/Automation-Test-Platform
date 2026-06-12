# Prompt Template: ICM Create Device Record

Use `@chrome` to execute `TC-ICM-006`.

## Required Inputs

- connector_type: `连接器-1`
- device_type: `标准设备`
- device_name: `Test_Ins01`
- device_ip: `192.168.16.11`
- device_port: `5900`
- vnc_password: `<configured locally>`
- allow_control: `是`
- device_status: `开启`

## Required Steps

1. Open `ICM > 设备信息`.
2. Open the add/create device form.
3. Fill the device form with the provided values.
4. Save the record and confirm it appears in the list.
5. Keep 3 screenshots: list entry, filled create form or submit state, final created row.

## Output Format

- case name
- environment
- preconditions
- key steps
- result
- failure point
- screenshot paths
