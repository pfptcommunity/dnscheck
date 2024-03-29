import argparse
import csv
import ipaddress
import os
import re
import sys
from typing import Union, Optional

import xlsxwriter
from dns import rdatatype, resolver, reversename
from dns.name import Name
from dns.rdatatype import RdataType
from dns.resolver import Answer

DATA_TYPE_DMARC = 'DMARC Data'
DATA_TYPE_SPF = 'SPF Data'
DATA_TYPE_MX = 'MX Data'
DATA_TYPE_PTR = 'PTR Data'
DATA_TYPE_A = 'A Data'

# Initialize a custom resolver
custom_resolver = resolver.Resolver()

# Pattern to match SPF record
spf_pattern = re.compile(r'^v=spf', re.IGNORECASE)

def validate_file_path(file_path: str) -> str:
    """Validate if the file path exists."""
    if not os.path.exists(file_path):
        raise argparse.ArgumentTypeError(f"File '{file_path}' does not exist.")
    return file_path


def validate_xlsx_file(file_path: str) -> str:
    """Validate if the file has a .xlsx extension."""
    if not file_path.lower().endswith('.xlsx'):
        raise argparse.ArgumentTypeError("File must have a .xlsx extension.")
    return file_path


def parse_ip_list(ip: str) -> str:
    """Validate if the IP address is valid."""
    try:
        ipaddress.ip_address(ip)
        return ip
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid IP address: {e}")


def dns_lookup(qname: Union[str, Name], rdtype: Union[RdataType, str], pattern: Optional[re.Pattern] = None) -> list:
    """Perform DNS lookup and return records."""
    try:
        answers = custom_resolver.resolve(qname, rdtype)
        records = []
        for rdata in answers:
            record_text = get_record_text(rdata)
            if pattern is None or pattern.match(record_text):
                records.append(record_text)
        return records
    except Exception as e:
        return [str(e)]


def get_record_text(rdata: Answer) -> str:
    """Get text representation of DNS record."""
    if rdata.rdtype in [rdatatype.A, rdatatype.CNAME, rdatatype.PTR]:
        return rdata.to_text().strip('.')
    elif rdata.rdtype == rdatatype.TXT:
        return ''.join(chunk.decode('utf-8') for chunk in rdata.strings)
    elif rdata.rdtype == rdatatype.MX:
        return rdata.exchange.to_text().strip('.')
    else:
        return rdata.to_text().strip('.')


def process_domain(host: str, args: argparse.Namespace, dns_data: dict) -> None:
    """Process DNS lookup for a single domain."""
    if args.dmarc_flag:
        dns_data.setdefault(DATA_TYPE_DMARC, {'max_cols': 0, 'data': []})
        data = dns_lookup(f'_dmarc.{host}', 'TXT')
        dns_data[DATA_TYPE_DMARC]['max_cols'] = max(len(data), dns_data[DATA_TYPE_DMARC]['max_cols'])
        dns_data[DATA_TYPE_DMARC]['data'].append([host] + data)

    if args.spf_flag:
        dns_data.setdefault(DATA_TYPE_SPF, {'max_cols': 0, 'data': []})
        data = dns_lookup(host, 'TXT', spf_pattern)
        dns_data[DATA_TYPE_SPF]['max_cols'] = max(len(data), dns_data[DATA_TYPE_SPF]['max_cols'])
        dns_data[DATA_TYPE_SPF]['data'].append([host] + data)

    if args.mx_flag:
        dns_data.setdefault(DATA_TYPE_MX, {'max_cols': 0, 'data': []})
        data = dns_lookup(host, 'MX')
        dns_data[DATA_TYPE_MX]['max_cols'] = max(len(data), dns_data[DATA_TYPE_MX]['max_cols'])
        dns_data[DATA_TYPE_MX]['data'].append([host] + data)

    if args.a_flag:
        dns_data.setdefault(DATA_TYPE_A, {'max_cols': 0, 'data': []})
        data = dns_lookup(host, 'A')
        dns_data[DATA_TYPE_A]['max_cols'] = max(len(data), dns_data[DATA_TYPE_A]['max_cols'])
        dns_data[DATA_TYPE_A]['data'].append([host] + data)

    if args.reverse_flag:
        dns_data.setdefault(DATA_TYPE_PTR, {'max_cols': 0, 'data': []})
        reversed_ip = reversename.from_address(host)
        data = dns_lookup(reversed_ip, 'PTR')
        dns_data[DATA_TYPE_PTR]['max_cols'] = max(len(data), dns_data[DATA_TYPE_PTR]['max_cols'])
        dns_data[DATA_TYPE_PTR]['data'].append([host] + data)


def write_to_excel(dns_data: dict, output_file: str) -> None:
    """Write DNS data to an Excel file."""
    workbook = xlsxwriter.Workbook(output_file)
    header_field = workbook.add_format()
    header_field.set_bold()
    dns_sheets = {}
    for name, meta in dns_data.items():
        header_name = name.upper().replace(' ', '_')
        dns_sheets[name] = workbook.add_worksheet(name)
        dns_sheets[name].write(0, 0, "Host/IP", header_field)
        col = 1
        for i in range(meta['max_cols']):
            dns_sheets[name].write(0, col, "{}_{}".format(header_name, i), header_field)
            col += 1
    for name, meta in dns_data.items():
        row = 1
        for row_data in meta['data']:
            col = 0
            for col_data in row_data:
                dns_sheets[name].write(row, col, col_data)
                col += 1
            row += 1
        dns_sheets[name].autofit()
    workbook.close()


def write_to_excel_compact(dns_data: dict, output_file: str) -> None:
    """Write DNS data to an Excel file."""
    workbook = xlsxwriter.Workbook(output_file)
    header_field = workbook.add_format()
    header_field.set_bold()
    dns_sheets = {}
    for name, meta in dns_data.items():
        header_name = name.upper().replace(' ', '_')
        dns_sheets[name] = workbook.add_worksheet(name)
        dns_sheets[name].write(0, 0, "Host/IP", header_field)
        dns_sheets[name].write(0, 1, header_name, header_field)
    for name, meta in dns_data.items():
        row = 1
        for row_data in meta['data']:
            dns_sheets[name].write(row, 0, row_data[0])
            cell_format = workbook.add_format({'text_wrap': True})
            cell_value = '\n'.join(row_data[1:])
            dns_sheets[name].write(row, 1, cell_value, cell_format)
            row += 1
        dns_sheets[name].autofit()
    workbook.close()


def main():
    # Argument parsing
    parser = argparse.ArgumentParser(prog="dnscheck", description="Bulk DNS Lookup Tool", formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=80))
    parser.add_argument('-i', '--input', metavar='<file>', dest="input_file", type=validate_file_path,
                        required=True, help='CSV file containing a list of domains')
    parser.add_argument("--input-type", choices=['txt', 'csv'], default='csv', dest="input_type",
                        help="Type of input file to process (txt or csv). (Default=csv)")
    parser.add_argument('--host-ip', metavar='IP/HOST', dest="host_field", type=str, required=False,
                        help='CSV field of host or IP. (default=Domain)')
    parser.add_argument("--ns", metavar='8.8.8.8', dest="ns", nargs='+', type=parse_ip_list,
                        help="List of DNS server addresses")
    parser.add_argument('--dmarc', action="store_true", dest="dmarc_flag", help='DMARC record lookup')
    parser.add_argument('--spf', action="store_true", dest="spf_flag", help='SPF record lookup')
    parser.add_argument('--mx', action="store_true", dest="mx_flag", help='MX record lookup')
    parser.add_argument('-a', '--forward', action="store_true", dest="a_flag", help='A record lookup')
    parser.add_argument('-x', '--reverse', action="store_true", dest="reverse_flag",
                        help='PTR record lookup, ip to host')
    parser.add_argument('-c', '--compact', action="store_true", dest="compact_flag",
                        help='Compact format will add multiple records to single column.')
    parser.add_argument('-o', '--output', metavar='<xlsx>', dest="output_file", type=validate_xlsx_file,
                        required=True, help='Output file')

    if len(sys.argv) == 1:
        parser.print_usage()  # Print usage information if no arguments are passed
        sys.exit(1)

    args = parser.parse_args()

    if args.input_type == 'csv' and not args.host_field:
        args.host_field = 'Domain'

    if args.input_type != 'csv' and args.host_field:
        parser.error("--host-ip can not be used with type '{}'".format(args.input_type))

    if args.input_file:
        print("Input file:", args.input_file)

    if args.ns:
        custom_resolver.nameservers = args.ns

    print("Nameserver(s):", custom_resolver.nameservers)

    dns_data = {}

    with open(args.input_file, 'r', encoding='utf-8-sig') as input_file:
        reader = csv.DictReader(input_file) if args.input_type == 'csv' else input_file
        for line in reader:
            host = line[args.host_field].strip() if args.input_type == 'csv' else line.strip()
            if not host:
                continue
            print("Processing:", host)
            process_domain(host, args, dns_data)

    if args.compact_flag:
        write_to_excel_compact(dns_data, args.output_file)
    else:
        write_to_excel(dns_data, args.output_file)

    print("Please see report: {}".format(args.output_file))


if __name__ == '__main__':
    main()
