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
        "input[placeholder*='手机']",
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
        "button:has-text('登录')",
        "role=button[name='登录']",
        "role=button[name='登 录']",
        "text=登录",
    ]

    login_success_candidates = [
        "text=数据营销",
        "text=搜索",
        "role=link[name='数据营销']",
        "role=button[name='数据营销']",
        "[class*='avatar']",
        "[class*='user-info']",
        "[class*='header-user']",
        ".user-name",
        "text=退出",
        "text=全球买家",
    ]

    login_page_marker_candidates = [
        "text=用户登录",
        "text=安全登录",
        "text=用户名",
        "text=密码",
        "button:has-text('安全登录')",
        "button:has-text('登录')",
        "input[placeholder*='验证码']",
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
        # ★ 最高优先级：Joinf 实际的 li 行结构（从用户提供的 HTML 确认）
        "li.row-is-see",
        "li[class*='row-is']",
        # Joinf 商业数据/海关数据 - 卡片式列表
        ":has(span:text('查看详情'))",
        ":has(.checkInfoBox)",
        "[class*='checkInfoBox']:scope",
        # 常见卡片/结果项类名
        "[class*='result-item']",
        "[class*='company-item']",
        "[class*='companyItem']",
        "[class*='card-item']",
        "[class*='card']:has(a):has(span)",
        "[class*='list-item']",
        # 通用容器
        "[class*='result'] [class*='item']",
        "[class*='result-list'] > div",
        "[class*='result-list'] [class*='card']",
        "[class*='list'] [class*='item']",
        "[class*='search-result'] [class*='item']",
        # ul/li 列表（后备）
        "ul.search-result-list > li",
        "ul.result-list > li",
        "ul.data-list > li",
        "ul[class*='result'] > li",
        "ul[class*='list'] > li",
        "div[class*='result-list'] > div[class*='item']",
        "div[class*='list'] > div[class*='item']",
        "div[class*='card-list'] > div[class*='card']",
        # 标准 table（后备）
        "table tbody tr",
        ".el-table__body tbody tr",
        ".el-table__row",
        ".ant-table-tbody > tr",
        ".el-table__body-wrapper tbody tr",
        ".vxe-table__body tbody tr",
        ".vxe-body--row",
        "div[role='table'] div[role='row']",
        ".el-table__body .el-table__row",
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

    # 详情页选择器 - 商业数据
    detail_row_link_candidates = [
        "table tbody tr td a",
        ".el-table__body tbody tr td a",
        ".table tbody tr td a",
        "table tbody tr td:first-child a",
    ]

    detail_row_clickable_candidates = [
        # ★ 最高优先级：Joinf 实际的 li 行结构
        "li.row-is-see",
        "li[class*='row-is']",
        # Joinf 卡片式列表中的可点击项（从HTML确认的结构）
        "[class*='checkInfoBox']:has(span:text('查看详情'))",  # 包含"查看详情"按钮的卡片容器
        "[class*='companyItem']",  # 可能的卡片容器类名
        "[class*='company-item']",
        "[class*='result-item']",
        "[class*='card-item']",
        "[class*='list-item']",
        # 更宽泛的选择器
        "[class*='result'] [class*='item']",
        "[class*='result-list'] > div",
        "[class*='result-list'] [class*='card']",
        "[class*='list'] [class*='item']",
        "[class*='search-result'] [class*='item']",
        # ul/li 列表
        "ul[class*='result'] > li",
        "ul[class*='list'] > li",
        "ul.search-result-list > li",
        "ul.result-list > li",
        # 公司名链接
        "a[href*='detail']",
        "a[href*='company']",
        "[class*='company-name'] a",
        "[class*='name'] a",
        # 标准 table
        "table tbody tr",
        ".el-table__body tbody tr",
        ".table tbody tr",
    ]

    # 解密/查看详情按钮
    decrypt_button_candidates = [
        # Joinf 实际的"查看详情"按钮（从HTML确认）
        "span:text('查看详情')",
        "span:has-text('查看详情')",
        "div.checkInfoBox span:text('查看详情')",
        "[class*='checkInfo'] span:text('查看详情')",
        "[class*='check-info'] span:text('查看详情')",
        # 其他可能形式
        "button:has-text('解密')",
        "a:has-text('解密')",
        "span:has-text('解密')",
        "[class*='decrypt']",
        "[class*='decode']",
        "button:has-text('查看联系方式')",
        "a:has-text('查看联系方式')",
        "button:has-text('获取联系方式')",
        "a:has-text('获取联系方式')",
        "button:has-text('查看')",
        "a:has-text('查看全部')",
        "button:has-text('解锁')",
        "a:has-text('解锁')",
        "span:has-text('解密查看')",
        "a:has-text('解密查看')",
        "[class*='unlock']",
        "[class*='reveal']",
        "button[class*='decrypt']",
        "a[class*='decrypt']",
    ]

    # 详情页字段
    detail_company_name_candidates = [
        ".company-name",
        ".company-name h1",
        ".company-name h2",
        "[class*='company'] h1",
        "[class*='company'] h2",
        ".detail-name",
        "h1.company",
        "h2.company",
    ]

    detail_country_candidates = [
        "[class*='country']",
        "[class*='nation']",
        "label:has-text('国家') + span",
        "label:has-text('国家') + div",
        "td:has-text('国家') + td",
    ]

    detail_city_candidates = [
        "[class*='city']",
        "[class*='region']",
        "label:has-text('城市') + span",
        "label:has-text('城市') + div",
        "td:has-text('城市') + td",
    ]

    detail_industry_candidates = [
        "[class*='industry']",
        "[class*='sector']",
        "label:has-text('行业') + span",
        "label:has-text('行业') + div",
        "td:has-text('行业') + td",
    ]

    detail_website_candidates = [
        "[class*='website'] a",
        "[class*='web'] a",
        "a[href]:has-text('www.')",
        "a[href]:has-text('http')",
        "label:has-text('网站') + a",
        "label:has-text('官网') + a",
    ]

    detail_description_candidates = [
        "[class*='description']",
        "[class*='intro']",
        "[class*='about']",
        "[class*='profile']",
        "label:has-text('简介') + span",
        "label:has-text('简介') + div",
        "label:has-text('公司简介') + span",
        "label:has-text('公司简介') + div",
        "td:has-text('公司简介') + td",
        "td:has-text('简介') + td",
    ]

    detail_phone_candidates = [
        "[class*='phone']",
        "[class*='tel']",
        "label:has-text('电话') + span",
        "label:has-text('电话') + div",
        "td:has-text('电话') + td",
        "label:has-text('手机') + span",
    ]

    detail_address_candidates = [
        "[class*='address']",
        "[class*='location']",
        "label:has-text('地址') + span",
        "label:has-text('地址') + div",
        "td:has-text('地址') + td",
    ]

    detail_product_candidates = [
        "[class*='product']",
        "[class*='goods']",
        "label:has-text('产品') + span",
        "label:has-text('产品') + div",
        "td:has-text('产品描述') + td",
        "td:has-text('产品') + td",
    ]

    # 详情页联系人列表
    detail_contact_list_candidates = [
        "[class*='contact-list'] tr",
        "[class*='contact'] tr",
        "[class*='person'] tr",
        "[class*='contact-list'] li",
        "[class*='contact'] li",
        "table:has(th:has-text('姓名')) tbody tr",
        "table:has(th:has-text('联系人')) tbody tr",
    ]

    detail_contact_name_candidates = [
        "td:nth-child(1)",
        "[class*='contact-name']",
        "[class*='person-name']",
    ]

    detail_contact_title_candidates = [
        "td:nth-child(2)",
        "[class*='contact-title']",
        "[class*='person-title']",
    ]

    detail_contact_email_candidates = [
        "td:nth-child(3)",
        "[class*='contact-email']",
        "[class*='person-email']",
    ]

    detail_contact_phone_candidates = [
        "td:nth-child(4)",
        "[class*='contact-phone']",
        "[class*='person-phone']",
    ]

    # 海关数据详情页
    customs_detail_row_link_candidates = [
        "table tbody tr td a",
        ".el-table__body tbody tr td a",
        ".table tbody tr td a",
    ]

    customs_buyer_detail_candidates = [
        "button:has-text('采购商详情')",
        "a:has-text('采购商详情')",
        "span:has-text('采购商详情')",
        "button:has-text('查看详情')",
        "a:has-text('查看详情')",
    ]

    customs_detail_background_candidates = [
        "[class*='background']",
        "[class*='company-info']",
        "label:has-text('公司背景') + span",
        "label:has-text('公司背景') + div",
        "td:has-text('公司背景') + td",
        "td:has-text('背景') + td",
    ]

    customs_detail_contact_candidates = [
        "[class*='contact']",
        "label:has-text('联系方式') + span",
        "label:has-text('联系方式') + div",
        "td:has-text('联系方式') + td",
    ]

    customs_detail_hs_code_candidates = [
        "[class*='hs-code']",
        "[class*='hscode']",
        "label:has-text('HS编码') + span",
        "label:has-text('HS编码') + div",
        "td:has-text('HS编码') + td",
    ]

    customs_detail_trade_date_candidates = [
        "label:has-text('交易日期') + span",
        "label:has-text('交易日期') + div",
        "td:has-text('交易日期') + td",
    ]

    customs_detail_frequency_candidates = [
        "label:has-text('频次') + span",
        "label:has-text('频次') + div",
        "td:has-text('频次') + td",
        "label:has-text('交易次数') + span",
    ]

    customs_detail_product_candidates = [
        "[class*='product']",
        "label:has-text('产品') + span",
        "label:has-text('产品描述') + span",
        "td:has-text('产品描述') + td",
    ]

    # 翻页
    pagination_next_button_candidates = [
        "text=下一页",
        "role=button[name='下一页']",
        ".ant-pagination-next:not(.ant-pagination-disabled)",
        ".el-pagination .btn-next:not([disabled])",
        "button:has-text('下一页'):not([disabled])",
        "a:has-text('下一页')",
        ".pagination .next:not(.disabled)",
        "li.next a",
    ]
