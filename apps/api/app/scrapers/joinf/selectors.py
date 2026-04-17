from __future__ import annotations


class JoinfSelectors:
    login_username_input_candidates = [
        "input:visible[type='text']",
        "input:visible:not([type])",
        "input[name='username']",
        "input[name='account']",
        "input[type='text']",
        "input[placeholder*='账号']",
        "input[placeholder*='用户名']",
        "input[placeholder*='邮箱']",
    ]

    login_password_input_candidates = [
        "input:visible[type='password']",
        "input[name='password']",
        "input[type='password']",
        "input[placeholder*='密码']",
    ]

    login_submit_candidates = [
        "button[type='submit']",
        "button:has-text('安全登录')",
        "role=button[name='登录']",
        "role=button[name='登 录']",
        "text=登录",
    ]

    login_success_candidates = [
        "text=数据营销",
        "role=link[name='数据营销']",
        "role=button[name='数据营销']",
        "[class*='avatar']",
        "[class*='user']",
    ]

    login_page_marker_candidates = [
        "text=用户登录",
        "text=安全登录",
        "text=用户名",
        "text=密码",
        "button:has-text('安全登录')",
        "button:has-text('登录')",
    ]

    data_marketing_nav_candidates = [
        "text=数据营销",
        "text='数据营销'",
        "role=link[name='数据营销']",
        "role=button[name='数据营销']",
    ]

    global_buyers_nav_candidates = [
        "text=全球买家",
        "text='全球买家'",
        "role=link[name='全球买家']",
        "role=button[name='全球买家']",
    ]

    global_buyers_direct_nav_candidates = [
        "a:has-text('全球买家')",
        "button:has-text('全球买家')",
        "text=全球买家",
    ]

    custom_info_entry_candidates = [
        "text=定制信息",
        "text='定制信息'",
        "text=定制",
        "role=button[name='定制信息']",
        "role=button[name='定制']",
    ]

    custom_keyword_input_candidates = [
        "input[placeholder*='关键词']",
        "input[placeholder*='产品']",
        "input[placeholder*='定制']",
    ]

    custom_country_input_candidates = [
        "input[placeholder*='国家']",
        "input[placeholder*='地区']",
        "input[placeholder*='市场']",
    ]

    custom_dropdown_input_candidates = [
        ".el-select-dropdown input.el-input__inner",
        ".el-popper input.el-input__inner",
        ".el-popper input[type='text']",
        "input[placeholder*='搜索']",
        "input[placeholder*='请输入']",
    ]

    custom_info_submit_candidates = [
        "button:has-text('确定')",
        "button:has-text('保存')",
        "button:has-text('完成')",
        "button:has-text('应用')",
        "button:has-text('查询')",
    ]

    business_data_nav_candidates = [
        "text=商业数据",
        "text='商业数据'",
        "role=link[name='商业数据']",
        "role=button[name='商业数据']",
    ]

    customs_data_nav_candidates = [
        "text=海关数据",
        "text='海关数据'",
        "role=link[name='海关数据']",
        "role=button[name='海关数据']",
    ]

    table_row_candidates = [
        "table tbody tr",
        ".table tbody tr",
        ".el-table__body tbody tr",
        ".ant-table-tbody > tr",
    ]

    pagination_next_candidates = [
        "text=下一页",
        "role=button[name='下一页']",
        ".ant-pagination-next",
        ".el-pagination .btn-next",
    ]

    search_input_candidates = [
        "input[placeholder*='关键词']",
        "input[placeholder*='搜索']",
        "input[type='text']",
    ]

    country_filter_candidates = [
        "input[placeholder*='国家']",
        "input[placeholder*='地区']",
        ".country-filter input",
    ]

    search_dropdown_input_candidates = [
        ".el-select-dropdown input.el-input__inner",
        ".el-popper input.el-input__inner",
        ".el-popper input[type='text']",
        "input[placeholder*='搜索']",
    ]

    country_dropdown_input_candidates = [
        ".el-select-dropdown input.el-input__inner",
        ".el-popper input.el-input__inner",
        ".el-popper input[type='text']",
        "input[placeholder*='国家']",
        "input[placeholder*='地区']",
        "input[placeholder*='搜索']",
    ]
